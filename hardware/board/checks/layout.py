"""PCB checks (SPEC.md "Automated checks" 2-4 and the silkscreen rules), on
the routed board, independent of the layout scripts' own bookkeeping.

Each check takes a Board (pcbnew board + netlist, below) and returns a list of
failure strings; empty = pass. Geometry comes from pcbnew's own item shapes
(TransformShapeToPolygon, zone fills) turned into shapely polygons, so the
checks see the copper that the gerbers will have.

    kicad-python layout.py [board.kicad_pcb]

Needs pcbnew (kicad-python in `nix develop .#hardware`) and shapely.
"""

import math
import os
import re
import sys

import pcbnew as K
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "layout"))
import board as B  # noqa: E402
import logo  # noqa: E402
import routes  # noqa: E402
from netlist import Netlist  # noqa: E402

MAXERR = K.FromMM(0.005)
TOL = 0.002   # mm, for geometry compares


def mm(v):
    return K.ToMM(v)


def xy(v):
    return (mm(v.x) - B.ORIGIN[0], mm(v.y) - B.ORIGIN[1])


def polyset_to_shapely(ps):
    polys = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        ext = [xy(o.CPoint(j)) for j in range(o.PointCount())]
        holes = []
        for k in range(ps.HoleCount(i)):
            h = ps.Hole(i, k)
            holes.append([xy(h.CPoint(j)) for j in range(h.PointCount())])
        if len(ext) >= 3:
            polys.append(Polygon(ext, holes).buffer(0))
    return unary_union(polys) if polys else Polygon()


def item_shape(item, layer, clearance=0):
    ps = K.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, K.FromMM(clearance), MAXERR, K.ERROR_INSIDE)
    return polyset_to_shapely(ps)


def pad_copper(p, layer):
    """A pad's copper on one layer: its flashed shape, or only the plated barrel
    where the pad has no ring on that layer (unconnected inner rings removed)."""
    if p.FlashLayer(layer):
        return item_shape(p, layer)
    from shapely.geometry import Point
    return Point(*xy(p.GetPosition())).buffer(mm(p.GetDrillSize().x) / 2, quad_segs=16)


class Board:
    """A pcbnew board plus the netlist it must match; shapes are cached."""

    def __init__(self, pcb, nl):
        self.pcb, self.nl = pcb, nl
        self.fps = {fp.GetReference(): fp for fp in pcb.GetFootprints()}
        self.pin_net = {(r, p): n for n, nodes in nl.nets.items() for r, p in nodes}

    @classmethod
    def load(cls, path=None, netlist=None):
        return cls(K.LoadBoard(path or B.PCB), Netlist.load(netlist or B.NETLIST))

    def pad(self, ref, num):
        for p in self.fps[ref].Pads():
            if p.GetNumber() == num:
                return p
        raise KeyError(f"{ref}.{num}")

    def tracks(self, net=None):
        return [t for t in self.pcb.GetTracks() if t.GetClass() == "PCB_TRACK"
                and (net is None or t.GetNetname() == net)]

    def vias(self, net=None):
        return [t for t in self.pcb.GetTracks() if t.GetClass() == "PCB_VIA"
                and (net is None or t.GetNetname() == net)]

    def zone_fill(self, net, layer):
        u = [polyset_to_shapely(z.GetFilledPolysList(layer)) for z in self.pcb.Zones()
             if z.GetNetname() == net and z.IsOnLayer(layer) and not z.GetIsRuleArea()]
        return unary_union(u) if u else Polygon()


# --- 2. parity -------------------------------------------------------------------

def check_parity(bd):
    """Every netlist part is on the board with its footprint, every pad carries
    the netlist net of (ref, pad) and pads the netlist leaves open carry none;
    nothing extra besides the board-only footprints."""
    f = []
    nl = bd.nl
    for ref, c in nl.comps.items():
        fp = bd.fps.get(ref)
        if fp is None:
            f.append(f"{ref}: in the netlist, not on the board")
            continue
        fpid = fp.GetFPID()
        name = f"{fpid.GetLibNickname()}:{fpid.GetLibItemName()}"
        if name != c["footprint"]:
            f.append(f"{ref}: footprint {name}, netlist says {c['footprint']}")
        for p in fp.Pads():
            if not p.GetNumber():
                if p.GetNetname():
                    f.append(f"{ref}: unnumbered pad has net {p.GetNetname()}")
                continue
            want = bd.pin_net.get((ref, p.GetNumber()), "")
            if p.GetNetname() != want:
                f.append(f"{ref}.{p.GetNumber()}: net {p.GetNetname() or '(none)'}, netlist {want or '(none)'}")
        pads = {p.GetNumber() for p in fp.Pads()}
        for (r, pin), n in bd.pin_net.items():
            if r == ref and pin not in pads:
                f.append(f"{ref}.{pin} ({n}) has no pad")
    for ref, fp in bd.fps.items():
        if ref not in nl.comps and ref not in B.BOARD_ONLY:
            f.append(f"{ref}: on the board, not in the netlist")
        if ref in B.BOARD_ONLY and any(p.GetNetname() for p in fp.Pads()):
            f.append(f"{ref}: board-only footprint has a connected pad")
    return f


# --- 4. layout -------------------------------------------------------------------

def check_top_side(bd):
    """Single-sided assembly: every footprint on the top side."""
    return [f"{r} is on the bottom side" for r, fp in sorted(bd.fps.items()) if fp.IsFlipped()]


def pair_class_width(cls):
    return (B.CAN_W, B.CAN_GAP) if cls == "CAN" else (B.USB_W, B.USB_GAP)


def in_zones(pt, zones):
    return any(x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1 for x0, y0, x1, y1, _ in zones)


def segs(tracks):
    return [(xy(t.GetStart()), xy(t.GetEnd()), mm(t.GetWidth())) for t in tracks]


def samples(a, c, step=0.1):
    n = max(1, int(math.dist(a, c) / step))
    return [(a[0] + (c[0] - a[0]) * i / n, a[1] + (c[1] - a[1]) * i / n) for i in range(n + 1)]


def check_pairs(bd):
    """Each pair: all copper on F.Cu, no vias, tracks at the impedance width
    (narrower only for the listed stubs), and coupled at width + gap outside the
    listed uncoupled zones."""
    f = []
    for name, (p, n, cls) in B.PAIRS.items():
        w, gap = pair_class_width(cls)
        zones = routes.UNCOUPLED.get(name, [])
        lines = {}
        for net in (p, n):
            ts = bd.tracks(net)
            if not ts:
                f.append(f"{name}: {net} has no tracks")
                continue
            for v in bd.vias(net):
                f.append(f"{name}: via on {net} at {xy(v.GetPosition())}")
            for t in ts:
                a, c = xy(t.GetStart()), xy(t.GetEnd())
                if t.GetLayer() != K.F_Cu:
                    f.append(f"{name}: {net} track on {t.GetLayerName()} at {a}")
                tw = mm(t.GetWidth())
                if abs(tw - w) > TOL:
                    stub = B.NARROW_STUBS.get(net)
                    near = stub and all(min(math.dist(q, xy(pd.GetPosition())) for pd in bd.fps[stub[0]].Pads()
                                            if pd.GetNetname() == net) <= stub[1] for q in (a, c))
                    if not (tw < w and near):
                        f.append(f"{name}: {net} track {tw:.3f} mm wide (pair width {w}) at {a}-{c}")
            lines[net] = unary_union([LineString([xy(t.GetStart()), xy(t.GetEnd())]) for t in ts
                                      if t.GetLayer() == K.F_Cu])
        if len(lines) < 2:
            continue
        pitch = w + gap
        for net, other in ((p, n), (n, p)):
            bad = []
            # the corners of the other line: a point opposite a mitred corner sits
            # up to sqrt(2) x pitch from it, so the check skips one pitch around each vertex
            verts = [Point(xy(e)) for t in bd.tracks(other) for e in (t.GetStart(), t.GetEnd())]
            vtree = STRtree(verts) if verts else None
            for t in bd.tracks(net):
                if abs(mm(t.GetWidth()) - w) > TOL:
                    continue
                ends = (xy(t.GetStart()), xy(t.GetEnd()))
                for q in samples(*ends):
                    if in_zones(q, zones):
                        continue
                    if min(math.dist(q, e) for e in ends) < 1.5 * pitch:
                        continue
                    if vtree is not None and len(vtree.query(Point(q).buffer(1.5 * pitch))):
                        continue
                    d = lines[other].distance(Point(q))
                    if abs(d - pitch) > 0.01:
                        bad.append((q, d))
            if bad:
                q, d = bad[0]
                f.append(f"{name}: {net} uncoupled outside its zones at {len(bad)} points, "
                         f"e.g. ({q[0]:.2f}, {q[1]:.2f}) is {d:.3f} mm from {other} (want {pitch:.3f})")
    return f


def copper_graph(bd, net):
    """Track centreline graph of one net on F.Cu, pads attached at their centres."""
    nodes = {}
    edges = []

    def node(q):
        # merge points within 2 um (float noise from IU -> mm), not by rounding,
        # which splits points that straddle a rounding boundary
        for k in nodes:
            if abs(k[0] - q[0]) < 0.002 and abs(k[1] - q[1]) < 0.002:
                return k
        k = (q[0], q[1])
        nodes[k] = []
        return k

    for t in bd.tracks(net):
        a, c = node(xy(t.GetStart())), node(xy(t.GetEnd()))
        edges.append((a, c, math.dist(a, c)))
    adj = {}
    for a, c, d in edges:
        adj.setdefault(a, []).append((c, d))
        adj.setdefault(c, []).append((a, d))
    # pads a line runs straight through (termination jumpers): a node at the centre
    for fp in bd.fps.values():
        for p in fp.Pads():
            if p.GetNetname() == net:
                adj.setdefault(node(xy(p.GetPosition())), [])
    # mid-segment T-junctions: join a node lying on another segment
    for k in list(adj):
        for a, c, d in edges:
            if k in (a, c):
                continue
            if LineString([a, c]).distance(Point(k)) < 1e-3:
                adj[k].append((a, math.dist(k, a)))
                adj[k].append((c, math.dist(k, c)))
                adj[a].append((k, math.dist(k, a)))
                adj[c].append((k, math.dist(k, c)))
    return adj


def path_length(adj, a, b):
    """Dijkstra over the track graph between the track ends nearest two pad centres."""
    import heapq

    def snap(q):
        best = min(adj, key=lambda k: math.dist(k, q)) if adj else None
        return best if best is not None and math.dist(best, q) < 0.05 else None

    s, t = snap(a), snap(b)
    if s is None or t is None:
        return None
    dist = {s: 0.0}
    pq = [(0.0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == t:
            return d
        if d > dist.get(u, 1e9):
            continue
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, 1e9):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return None


def pair_lengths(bd):
    """{pair: [(terminal, len_P, len_N)]} from the reference terminal."""
    out = {}
    for name, terms in B.PAIR_TERMINALS.items():
        p, n, _ = B.PAIRS[name]
        gp, gn = copper_graph(bd, p), copper_graph(bd, n)
        (rp, rn) = terms[0]
        a_p, a_n = xy(bd.pad(*rp).GetPosition()), xy(bd.pad(*rn).GetPosition())
        rows = []
        for tp, tn in terms[1:]:
            lp = path_length(gp, a_p, xy(bd.pad(*tp).GetPosition()))
            ln = path_length(gn, a_n, xy(bd.pad(*tn).GetPosition()))
            rows.append((f"{tp[0]}.{tp[1]}/{tn[0]}.{tn[1]}", lp, ln))
        out[name] = rows
    return out


def check_mismatch(bd):
    """H vs L copper length from the reference end to each device, < 1 mm."""
    f = []
    for name, rows in pair_lengths(bd).items():
        for term, lp, ln in rows:
            if lp is None or ln is None:
                f.append(f"{name}: no track path to {term}")
            elif abs(lp - ln) >= B.MISMATCH_MAX:
                f.append(f"{name}: to {term} P {lp:.2f} mm vs N {ln:.2f} mm, mismatch {abs(lp - ln):.2f} mm")
    return f


def check_reference_plane(bd):
    """Under every pair track (outside the header pin fields, whose PTH antipads
    are unavoidable) the In1 GND fill is unbroken across the track width plus
    2 x the prepreg height: no split, no void, no other net."""
    f = []
    gnd = bd.zone_fill("GND", K.In1_Cu)
    # header pin fields, and the USB protector whose own GND/VBUS vias sit
    # between the lines it protects
    pinfields = [bd.fps[r].GetCourtyard(K.F_CrtYd) for r in ("J1", "J2", "U9")]
    pinfields = unary_union([polyset_to_shapely(c) for c in pinfields[:2]] +
                            [polyset_to_shapely(pinfields[2]).buffer(1.3)])   # U9 and its two vias
    for name, (p, n, cls) in B.PAIRS.items():
        for net in (p, n):
            bad = []
            for t in bd.tracks(net):
                r = mm(t.GetWidth()) / 2 + B.REF_MARGIN
                for q in samples(xy(t.GetStart()), xy(t.GetEnd()), 0.25):
                    disc = Point(q).buffer(r, 16)
                    if pinfields.contains(Point(q)):
                        continue
                    if not gnd.buffer(TOL).contains(disc):
                        bad.append(q)
            if bad:
                f.append(f"{name}: {net} leaves the In1 GND plane at {len(bad)} points, e.g. "
                         f"({bad[0][0]:.2f}, {bad[0][1]:.2f})")
    return f


def check_12v_width(bd):
    """12 V input tracks at least 0.5 mm (SPEC "PCB")."""
    f = []
    for net in B.NET_CLASSES["12V"][2]:
        for t in bd.tracks(net):
            if mm(t.GetWidth()) < B.V12_W - TOL:
                f.append(f"{net}: {mm(t.GetWidth()):.3f} mm track at {xy(t.GetStart())}")
    return f


def check_keepouts(bd):
    """Header mating faces: no other courtyard within the header body grown by
    HEADER_KEEPOUT. USB-C: receptacle front at the bottom edge, plug zone clear."""
    f = []
    court = {r: polyset_to_shapely(fp.GetCourtyard(K.F_CrtYd)) for r, fp in bd.fps.items()}
    for r in ("J1", "J2"):
        body = unary_union([item_shape(s, K.F_Fab) for s in bd.fps[r].GraphicalItems()
                            if s.GetLayer() == K.F_Fab and s.GetClass() == "PCB_SHAPE"])
        keep = box(*body.bounds).buffer(B.HEADER_KEEPOUT, join_style="mitre")
        for o, c in court.items():
            if o != r and not c.is_empty and c.intersection(keep).area > 1e-6:
                f.append(f"{o} intrudes on {r}'s mating keepout")
    j3 = bd.fps["J3"]
    fab = unary_union([item_shape(s, K.F_Fab) for s in j3.GraphicalItems()
                       if s.GetLayer() == K.F_Fab and s.GetClass() == "PCB_SHAPE"])
    if not j3.GetOrientationDegrees() % 360 == 0:
        f.append(f"J3 rotated {j3.GetOrientationDegrees()}: its opening must face the bottom edge")
    front = fab.bounds[3]
    lo, hi = B.USB_EDGE_TOL
    if not (B.H + lo <= front <= B.H + hi):
        f.append(f"J3 front at y={front:.2f}, board edge at {B.H} (allowed {lo}..+{hi})")
    cx = xy(j3.GetPosition())[0]
    plug = box(cx - B.USB_PLUG_HALF_W, B.H - B.USB_PLUG_DEPTH, cx + B.USB_PLUG_HALF_W, B.H + 5)
    for o, c in court.items():
        if o != "J3" and not c.is_empty and c.intersection(plug).area > 1e-6:
            f.append(f"{o} is in the USB plug zone at the edge")
    return f


# --- safety net, on copper ------------------------------------------------------

def copper_islands(bd):
    """Union-find over every copper item by physical overlap, per layer; returns
    {(ref, pad): island id} and the island id of every item."""
    items = []   # (key, layer, geom)
    keys = []
    for ref, fp in bd.fps.items():
        for p in fp.Pads():
            k = ("pad", ref, p.GetNumber(), tuple(round(v, 3) for v in xy(p.GetPosition())))
            keys.append(k)
            for layer in (K.F_Cu, K.In1_Cu, K.In2_Cu, K.B_Cu):
                if p.IsOnLayer(layer) and p.IsOnCopperLayer():
                    if p.GetAttribute() == K.PAD_ATTRIB_NPTH:
                        continue
                    g = pad_copper(p, layer)
                    if not g.is_empty:
                        items.append((k, layer, g))
    for i, t in enumerate(bd.pcb.GetTracks()):
        k = ("trk", i)
        keys.append(k)
        for layer in (K.F_Cu, K.In1_Cu, K.In2_Cu, K.B_Cu):
            if t.IsOnLayer(layer):
                items.append((k, layer, item_shape(t, layer)))
    for i, z in enumerate(bd.pcb.Zones()):
        if z.GetIsRuleArea():
            continue
        for layer in (K.F_Cu, K.In1_Cu, K.In2_Cu, K.B_Cu):
            if z.IsOnLayer(layer):
                g = polyset_to_shapely(z.GetFilledPolysList(layer))
                for j, part in enumerate(getattr(g, "geoms", [g])):
                    if not part.is_empty:
                        k = ("zone", i, layer, j)
                        keys.append(k)
                        items.append((k, layer, part))
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for layer in (K.F_Cu, K.In1_Cu, K.In2_Cu, K.B_Cu):
        li = [(k, g) for k, lay, g in items if lay == layer]
        tree = STRtree([g for _, g in li])
        for idx, (k, g) in enumerate(li):
            for j in tree.query(g, predicate="intersects"):
                if j > idx:
                    a, b = find(k), find(li[j][0])
                    if a != b:
                        parent[a] = b
    pads = {}
    for k in keys:
        if k[0] == "pad":
            pads.setdefault((k[1], k[2]), set()).add(find(k))
    return pads, find


def check_copper_safety(bd):
    """By copper geometry alone: no island joins two netlist nets (or a net and
    an open pad), every net is one island, the relay NC contacts reach the
    car-side CAN1 lines and COM the ADAS side, the two CAN1 halves touch only
    through the relay, and box pins J2.9/J2.11 have no copper at all."""
    f = []
    pads, _ = copper_islands(bd)
    island_nets = {}
    for (ref, num), isl in pads.items():
        n = bd.pin_net.get((ref, num)) or f"(open {ref}.{num})"
        for i in isl:
            island_nets.setdefault(i, set()).add(n)
    for i, ns in island_nets.items():
        if len(ns) > 1:
            f.append(f"copper short between {sorted(ns)}")
    for net, nodes in bd.nl.nets.items():
        isl = set()
        for r, p in nodes:
            isl |= pads.get((r, p), set())
        if len(nodes) > 1 and len(isl) > 1:
            f.append(f"{net} is not connected in copper ({len(isl)} islands)")

    def one(ref, num):
        s = pads.get((ref, num), set())
        return next(iter(s)) if len(s) == 1 else None

    for com, nc, adas, car in (("11", "12", ("J1", "9"), [("J1", "8"), ("J2", "8")]),
                               ("21", "22", ("J1", "11"), [("J1", "7"), ("J2", "7")])):
        if one("K1", com) is None or one("K1", com) != one(*adas):
            f.append(f"relay COM K1.{com} does not reach ADAS-side {adas[0]}.{adas[1]} in copper")
        for c in car:
            if one("K1", nc) is None or one("K1", nc) != one(*c):
                f.append(f"relay NC K1.{nc} does not reach car-side {c[0]}.{c[1]} in copper")
        if one("K1", com) is not None and one("K1", com) == one("K1", nc):
            f.append(f"relay COM K1.{com} and NC K1.{nc} are joined in copper (bypasses the contact)")
    # K2 switches the car-side termination: its COM pads sit on the car-side lines,
    # its NO pads reach only the termination jumpers (a short would be caught above)
    for com, car in (("11", ("J2", "8")), ("21", ("J2", "7"))):
        if "K2" in bd.fps and (one("K2", com) is None or one("K2", com) != one(*car)):
            f.append(f"relay COM K2.{com} does not reach car-side {car[0]}.{car[1]} in copper")
    # J2.9/J2.11: no track or zone may touch them
    for num in ("9", "11"):
        pd = bd.pad("J2", num)
        g = {lay: pad_copper(pd, lay) for lay in (K.F_Cu, K.B_Cu, K.In1_Cu, K.In2_Cu)}
        for t in bd.pcb.GetTracks():
            for lay, pg in g.items():
                if t.IsOnLayer(lay) and item_shape(t, lay).intersects(pg):
                    f.append(f"J2.{num} touched by a {t.GetClass()} of {t.GetNetname() or 'no net'}")
        for z in bd.pcb.Zones():
            for lay, pg in g.items():
                if z.IsOnLayer(lay) and polyset_to_shapely(z.GetFilledPolysList(lay)).intersects(pg):
                    f.append(f"J2.{num} touched by the {z.GetNetname()} zone on {K.LayerName(lay) if hasattr(K, 'LayerName') else lay}")
    return f


# --- silkscreen ---------------------------------------------------------------

def silk_items(bd, layer):
    out = []
    for d in bd.pcb.GetDrawings():
        if d.GetLayer() == layer:
            out.append(("board", d))
    for r, fp in bd.fps.items():
        for g in fp.GraphicalItems():
            if g.GetLayer() == layer:
                out.append((r, g))
        for fld in fp.GetFields():
            if fld.GetLayer() == layer and fld.IsVisible():
                out.append((r, fld))
    return out


def logo_shape(bd):
    """The leaf's exposed copper: the LOGO footprint's pad on F.Cu."""
    lg = bd.fps.get("LOGO")
    if lg is None:
        return None
    return unary_union([item_shape(p, K.F_Cu) for p in lg.Pads() if p.IsOnLayer(K.F_Cu)])


def check_silk(bd):
    """The copper leaf: on the top, no net, a mask opening and no paste, lines
    and gaps at least 0.15 mm, about 10.5 mm wide. On both sides, no
    silkscreen within silk_to_pad of a pad's solder-mask opening, none off the
    board."""
    f = []
    shape = logo_shape(bd)
    if shape is None or shape.is_empty:
        f.append("no LOGO footprint with copper")
    else:
        if bd.fps["LOGO"].IsFlipped():
            f.append("logo is on the bottom side")
        for p in bd.fps["LOGO"].Pads():
            if p.GetNetname():
                f.append(f"logo copper is on net {p.GetNetname()}")
            if not p.IsOnLayer(K.F_Mask) or p.IsOnLayer(K.F_Paste):
                f.append("logo copper needs a mask opening and no paste")
        thin, gaps = logo.min_feature_violations(shape)
        if thin > logo.EPS_AREA:
            f.append(f"logo has lines under {B.JLC['silk_width_min']} mm ({thin:.4f} mm^2)")
        if gaps > logo.EPS_AREA:
            f.append(f"logo has gaps under {B.JLC['silk_width_min']} mm ({gaps:.4f} mm^2)")
        w = shape.bounds[2] - shape.bounds[0]
        if not 10.0 <= w <= 11.0:
            f.append(f"logo is {w:.2f} mm wide (SPEC: about 10.5)")
    outline = box(0, 0, B.W, B.H).buffer(-0.1)
    for silk, mask_layer in ((K.F_SilkS, K.F_Mask), (K.B_SilkS, K.B_Mask)):
        mask = [item_shape(p, mask_layer) for fp in bd.fps.values() for p in fp.Pads() if p.IsOnLayer(mask_layer)]
        mask += [item_shape(v, mask_layer) for v in bd.vias() if v.IsOnLayer(mask_layer)]
        mask = unary_union(mask).buffer(B.JLC["silk_to_pad"] - TOL)
        for who, it in silk_items(bd, silk):
            g = item_shape(it, silk)
            if g.is_empty:
                continue
            if g.intersection(mask).area > 1e-5:
                f.append(f"{'top' if silk == K.F_SilkS else 'bottom'} silkscreen of {who} within "
                         f"{B.JLC['silk_to_pad']} mm of a solder-mask opening")
            if not outline.contains(g):
                f.append(f"silkscreen of {who} runs off the board")
    return f


LABEL_RE = re.compile(r"^(\d+) .+ / (\d+) ")
LABEL_Y_TOL = 0.3     # mm: a pin label's centre to its pin row
LABEL_GAP = 5.0       # mm: the most a label's near end may sit from its header's pads


def check_pin_labels(bd):
    """Back-side pin labels: each header has one per pin row (n odd / n+1),
    centred within LABEL_Y_TOL of that row's pins, beside the header on its
    inner side, its near end clear of the pads and within LABEL_GAP of them."""
    f = []
    rows = {"J1": {}, "J2": {}}
    inner = {r: xy(bd.pad(r, "2" if r == "J1" else "1").GetPosition())[0] for r in rows}
    for who, it in silk_items(bd, K.B_SilkS):
        if it.GetClass() != "PCB_TEXT":
            continue
        m = LABEL_RE.match(it.GetText())
        if not m:
            continue
        odd, even = int(m.group(1)), int(m.group(2))
        g = item_shape(it, K.B_SilkS)
        x0, y0, x1, y1 = g.bounds
        ref = min(rows, key=lambda r: abs((x0 + x1) / 2 - inner[r]))
        name = f"{ref} label '{it.GetText().strip()}'"
        if even != odd + 1 or odd % 2 == 0:
            f.append(f"{name}: not a pin row")
            continue
        rows[ref].setdefault(odd, []).append(name)
        py = xy(bd.pad(ref, str(odd)).GetPosition())[1]
        if abs((y0 + y1) / 2 - py) > LABEL_Y_TOL:
            f.append(f"{name}: centre at y={(y0 + y1) / 2:.2f}, its pins at y={py:.2f}")
        r = 1.5 / 2                                    # iGrid pad radius
        gap = x0 - (inner[ref] + r) if ref == "J1" else (inner[ref] - r) - x1
        if not B.JLC["silk_to_pad"] <= gap <= LABEL_GAP:
            f.append(f"{name}: x {x0:.2f}..{x1:.2f}, {gap:.2f} mm from {ref}'s inner row "
                     f"(wanted {B.JLC['silk_to_pad']} to {LABEL_GAP}, on its inner side)")
    for ref, got in rows.items():
        for odd in range(1, 18, 2):
            if len(got.get(odd, [])) != 1:
                f.append(f"{ref}: {len(got.get(odd, []))} labels for pins {odd}/{odd + 1}")
    return f


def ipc2221_internal_amps(width_mm, rise_c=10.0, cu_mm=None):
    """IPC-2221 internal-conductor current: I = 0.024 dT^0.44 A^0.725, A in mil^2.
    Conservative next to IPC-2152, which rates internal conductors higher."""
    a = (width_mm / 0.0254) * ((cu_mm or B.INNER_CU) / 0.0254)
    return 0.024 * rise_c ** 0.44 * a ** 0.725


# a +3V3 via's plane connection: via radius, thermal gap and spoke, then the
# erosion itself (IN2_NECK_MIN / 2): its region must start within this
IN2_REACH = 0.3 + 0.25 + 0.3 + 0.5


def check_in2(bd):
    """In2 is the +3V3 plane: only the VIN12 pass-throughs and short repair hops
    (<= IN2_HOP_MAX per net) may run on it, and its +3V3 fill stays one region
    with no neck under IN2_NECK_MIN, which must carry the 3V3 load with margin."""
    f = []
    runs = {}
    for t in bd.tracks():
        if t.GetLayer() != K.In2_Cu or t.GetNetname() in B.IN2_NETS:
            continue
        runs.setdefault(t.GetNetname(), []).append(mm(t.GetLength()))
    for net, ls in runs.items():
        if sum(ls) > B.IN2_HOP_MAX:
            f.append(f"{net} runs {sum(ls):.1f} mm on In2 (hops are limited to {B.IN2_HOP_MAX} mm)")
    fill = bd.zone_fill("+3V3", K.In2_Cu)
    parts = [p for p in getattr(fill, "geoms", [fill]) if p.area > 1.0]
    if len(parts) != 1:
        f.append(f"+3V3 plane on In2 is {len(parts)} regions")
    # Erode by half the neck: what stays joined is joined by IN2_NECK_MIN or more.
    # Only regions that serve a +3V3 connection count: a dead-end pocket the
    # vias cut off (nothing draws current through its neck) is harmless.
    eroded = fill.buffer(-B.IN2_NECK_MIN / 2 * 0.999)
    regions = [p for p in getattr(eroded, "geoms", [eroded]) if not p.is_empty]
    conns = [xy(v.GetPosition()) for v in bd.vias() if v.GetNetname() == "+3V3"]
    conns += [xy(p.GetPosition()) for fp in bd.fps.values() for p in fp.Pads()
              if p.GetNetname() == "+3V3" and p.IsOnLayer(K.In2_Cu) and p.FlashLayer(K.In2_Cu)]
    served, choked = set(), []
    for c in conns:
        pc = Point(c)
        d, i = min(((r.distance(pc), i) for i, r in enumerate(regions)), default=(1e9, -1))
        if d > IN2_REACH:
            choked.append(c)
        else:
            served.add(i)
    if len(served) > 1:
        f.append(f"+3V3 plane on In2 has a neck under {B.IN2_NECK_MIN} mm between its connections "
                 f"({len(served)} regions after eroding)")
    for c in choked[:3]:
        f.append(f"+3V3 plane on In2: the connection at ({c[0]:.2f}, {c[1]:.2f}) sits behind a neck under {B.IN2_NECK_MIN} mm")
    amps = ipc2221_internal_amps(B.IN2_NECK_MIN)
    if amps < 2 * B.V3V3_LOAD:
        f.append(f"a {B.IN2_NECK_MIN} mm In2 neck carries {amps:.2f} A, under 2 x the {B.V3V3_LOAD} A load")
    return f


MARK_REACH = 1.0    # mm: a cathode mark lies within this beyond pad 1's solder-mask opening
MARK_SPAN = 0.5     # ... and covers at least this fraction of the pad's width


def check_polarity_marks(bd):
    """Every diode and LED (D<n> with pads 1 = cathode and 2) has a cathode mark
    on the top silkscreen: silkscreen within MARK_REACH beyond pad 1's opening,
    on the side away from pad 2, across at least MARK_SPAN of the pad's width."""
    f = []
    drawings = [item_shape(d, K.F_SilkS) for d in bd.pcb.GetDrawings() if d.GetLayer() == K.F_SilkS]
    for ref, fp in sorted(bd.fps.items()):
        if not re.fullmatch(r"D\d+", ref) or sorted(p.GetNumber() for p in fp.Pads()) != ["1", "2"]:
            continue
        p1, p2 = bd.pad(ref, "1"), bd.pad(ref, "2")
        c1, c2 = xy(p1.GetPosition()), xy(p2.GetPosition())
        d = math.dist(c1, c2)
        u = ((c1[0] - c2[0]) / d, (c1[1] - c2[1]) / d)
        v = (-u[1], u[0])
        m = item_shape(p1, K.F_Mask)
        pts = [q for g in getattr(m, "geoms", [m]) for q in g.exterior.coords]
        reach = max((x - c1[0]) * u[0] + (y - c1[1]) * u[1] for x, y in pts)
        half = max(abs((x - c1[0]) * v[0] + (y - c1[1]) * v[1]) for x, y in pts)
        zone = Polygon([(c1[0] + s * u[0] + t * v[0], c1[1] + s * u[1] + t * v[1])
                        for s, t in ((reach, -half), (reach + MARK_REACH, -half), (reach + MARK_REACH, half), (reach, half))])
        silk = unary_union([item_shape(g, K.F_SilkS) for g in fp.GraphicalItems() if g.GetLayer() == K.F_SilkS] + drawings)
        hit = silk.intersection(zone)
        pts = [q for g in getattr(hit, "geoms", [hit]) if hasattr(g, "exterior") for q in g.exterior.coords]
        span = [(x - c1[0]) * v[0] + (y - c1[1]) * v[1] for x, y in pts]
        if not span or max(span) - min(span) < MARK_SPAN * 2 * half - TOL:
            f.append(f"{ref}: no cathode mark on the silkscreen beyond pad 1")
    return f


# only the 12 V nets: IGN carries the comma's own supply (amps), where one
# 0.3 mm via is the weak link; the 5 V rails, VBUS and the coil return carry at
# most ~0.5 A, well within one via
POWER_VIA_NETS = tuple(B.NET_CLASSES["12V"][2])
TWIN_REACH = 1.5    # mm


def check_power_vias(bd):
    """A 12 V net never changes layer through a single via: every via on one
    has another via of its net within TWIN_REACH. The buck's
    switch node has no via at all."""
    f = []
    for net in POWER_VIA_NETS:
        pos = [xy(v.GetPosition()) for v in bd.vias(net)]
        for q in pos:
            if not any(0.001 < math.dist(q, o) <= TWIN_REACH for o in pos):
                f.append(f"{net}: lone via at ({q[0]:.2f}, {q[1]:.2f}), no second via within {TWIN_REACH} mm")
    for v in bd.vias("BUCK_SW"):
        f.append(f"BUCK_SW: via at {xy(v.GetPosition())} (the switch node stays on F.Cu)")
    return f


def check_switch_node_clear(bd):
    """No copper but GND on B.Cu under the buck's switch node or L1 (their
    F.Cu copper and L1's courtyard, grown by board.SW_QUIET); nothing else
    on F.Cu inside L1's courtyard."""
    f = []
    sw = [item_shape(p, K.F_Cu) for fp in bd.fps.values() for p in fp.Pads() if p.GetNetname() == "BUCK_SW"]
    sw += [item_shape(t, K.F_Cu) for t in bd.tracks("BUCK_SW")]
    l1 = polyset_to_shapely(bd.fps["L1"].GetCourtyard(K.F_CrtYd))
    quiet = unary_union(sw + [l1]).buffer(B.SW_QUIET)
    for t in bd.pcb.GetTracks():
        n = t.GetNetname()
        if n in ("GND", "BUCK_SW"):
            continue
        if t.IsOnLayer(K.B_Cu) and item_shape(t, K.B_Cu).intersects(quiet):
            f.append(f"{n} {t.GetClass()[4:].lower()} on B.Cu at {xy(t.GetStart())} under the switch node / L1")
        elif t.GetClass() == "PCB_TRACK" and t.GetLayer() == K.F_Cu and n != "+5V_IGN" and item_shape(t, K.F_Cu).intersects(l1):
            f.append(f"{n} track on F.Cu at {xy(t.GetStart())} inside L1's courtyard")
    return f


STITCH_REACH = 3.5    # mm: along the edge, a GND via within this of every point where the pours reach
STITCH_INSET = 1.0


def gnd_stitches(bd):
    """Points where an outer GND pour reaches In1: GND vias and In1-connected
    GND through-hole pads."""
    pts = [xy(v.GetPosition()) for v in bd.vias("GND")]
    pts += [xy(p.GetPosition()) for fp in bd.fps.values() for p in fp.Pads()
            if p.GetNetname() == "GND" and p.GetAttribute() == K.PAD_ATTRIB_PTH and p.FlashLayer(K.In1_Cu)]
    return pts


def check_gnd_stitching(bd):
    """No outer-layer GND pour island reaches In1 through fewer than two
    stitches (vias or plated GND pins), and along the board edge, wherever the
    F.Cu and B.Cu pours both leave room for a via within 1.5 mm of the edge
    inset, a stitch sits within STITCH_REACH (outside the via keepout strip
    beside J2)."""
    f = []
    st = [Point(q) for q in gnd_stitches(bd)]
    for lay, name in ((K.F_Cu, "F.Cu"), (K.B_Cu, "B.Cu")):
        fill = bd.zone_fill("GND", lay)
        for isl in getattr(fill, "geoms", [fill]):
            if isl.is_empty:
                continue
            n = sum(1 for p in st if isl.distance(p) < 0.05)
            if n < 2:
                c = isl.representative_point()
                f.append(f"GND pour island on {name} at ({c.x:.2f}, {c.y:.2f}), {isl.area:.2f} mm^2, "
                         f"reaches In1 through {n} via(s)")
    # where both pours leave room for a via (its ring plus 0.05 mm inside each fill)
    room = bd.zone_fill("GND", K.F_Cu).intersection(bd.zone_fill("GND", K.B_Cu)).buffer(-0.35)
    keep = unary_union([box(*k) for k in routes.VIA_KEEPOUT])
    ring = box(0, 0, B.W, B.H).buffer(-STITCH_INSET).exterior
    tree = STRtree(st) if st else None
    gaps = []
    for i in range(int(ring.length / 0.5)):
        q = ring.interpolate(i * 0.5)
        if keep.contains(q) or room.distance(q) > 1.5:
            continue
        if tree is None or not len(tree.query(q.buffer(STITCH_REACH))):
            gaps.append(q)
    if gaps:
        f.append(f"board edge: {len(gaps)} points of GND pour with no stitch within {STITCH_REACH} mm, "
                 f"e.g. ({gaps[0].x:.2f}, {gaps[0].y:.2f})")
    return f


MCU_12V_CLEAR = 3.0    # mm
SUPPLY_12V = ("VIN_PROT", "IGN_FUSED")


def check_12v_off_mcu(bd):
    """The board's own 12 V supply (after the fuse) stays out of the MCU's
    area: no VIN_PROT or IGN_FUSED copper within MCU_12V_CLEAR of U1's
    courtyard; only the divided IGN_SENSE travels there."""
    f = []
    keep = polyset_to_shapely(bd.fps["U1"].GetCourtyard(K.F_CrtYd)).buffer(MCU_12V_CLEAR)
    for net in SUPPLY_12V:
        for t in bd.pcb.GetTracks():
            if t.GetNetname() != net:
                continue
            for lay in (K.F_Cu, K.B_Cu):
                if t.IsOnLayer(lay) and item_shape(t, lay).intersects(keep):
                    f.append(f"{net} {t.GetClass()[4:].lower()} on {K.LayerName(lay) if hasattr(K, 'LayerName') else lay} "
                             f"at {xy(t.GetStart())} is within {MCU_12V_CLEAR} mm of the MCU")
    return f


VIA_HOLE_WEB = 0.15   # mm, a via's hole edge to the nearest SMD pad, at least


def check_via_pads(bd):
    """No via in or touching an SMD pad, its own net's included: the via's ring
    clear of every SMD pad's copper on the outer layers (no overlap, not even
    touching), so the hole edge keeps at least VIA_HOLE_WEB of copper web."""
    f = []
    pads = []
    for r, fp in bd.fps.items():
        for p in fp.Pads():
            if p.GetAttribute() == K.PAD_ATTRIB_SMD:
                for lay in (K.F_Cu, K.B_Cu):
                    if p.IsOnLayer(lay):
                        pads.append((f"{r}.{p.GetNumber() or 'pad'}", lay, item_shape(p, lay)))
    tree = STRtree([g for _, _, g in pads])
    for v in bd.vias():
        c = Point(xy(v.GetPosition()))
        ring = c.buffer(mm(v.GetWidth(K.F_Cu)) / 2, 32)
        hole = mm(v.GetDrillValue()) / 2
        for i in tree.query(ring.buffer(VIA_HOLE_WEB + 0.2)):
            name, lay, g = pads[i]
            if not v.IsOnLayer(lay):
                continue
            web = g.distance(c) - hole
            if ring.distance(g) <= TOL or web < VIA_HOLE_WEB - TOL:
                f.append(f"via ({v.GetNetname()}) at ({c.x:.2f}, {c.y:.2f}) touches SMD pad {name} "
                         f"(hole edge {web:.3f} mm from the pad)")
    return f


CHECKS = [check_parity, check_top_side, check_pairs, check_mismatch, check_reference_plane,
          check_12v_width, check_keepouts, check_copper_safety, check_silk, check_pin_labels, check_in2,
          check_via_pads, check_polarity_marks, check_power_vias, check_gnd_stitching, check_12v_off_mcu,
          check_switch_node_clear]


def run(bd):
    return {c.__name__: c(bd) for c in CHECKS}


def report(bd):
    """Numbers worth printing: pair lengths and mismatch."""
    lines = []
    for name, rows in pair_lengths(bd).items():
        for term, lp, ln in rows:
            if lp is not None and ln is not None:
                lines.append(f"  {name:10s} to {term:14s} P {lp:6.2f}  N {ln:6.2f}  mismatch {abs(lp - ln):.2f} mm")
    return "\n".join(lines)


if __name__ == "__main__":
    bd = Board.load(sys.argv[1] if len(sys.argv) > 1 else None)
    bad = 0
    for name, fails in run(bd).items():
        print(f"{'ok  ' if not fails else 'FAIL'} {name}")
        for x in fails[:20]:
            print("      " + x)
        bad += bool(fails)
    print(report(bd))
    sys.exit(1 if bad else 0)
