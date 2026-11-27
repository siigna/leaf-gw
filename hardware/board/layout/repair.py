"""Finish the connections freerouting leaves open, with a small grid router.

freerouting gets all but a handful of connections on this board and then stops
improving. For those few, repair() runs A* on a 0.05 mm grid over F.Cu and
B.Cu (8-way moves, vias between them), against every other net's copper grown
by the clearance plus half the track width, the board edge, and the pairs'
via keepout (the same reference-plane margin the checks enforce). Deterministic:
fixed grid, fixed costs, ties broken by coordinates.
"""

import heapq
import math

import numpy as np
import pcbnew as K
import shapely
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

import board as B

GRID = 0.05
VIA_COST = 3.0      # mm-equivalent
TURN_COST = 0.2
LAYERS = (K.F_Cu, K.B_Cu)
LAYERS3 = (K.F_Cu, K.B_Cu, K.In2_Cu)   # In2 (the +3V3 plane) only for the last leftovers


def _poly(item, layer, grow=0.0):
    ps = K.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, K.FromMM(grow), K.FromMM(0.005), K.ERROR_OUTSIDE)
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        pts = [(K.ToMM(o.CPoint(j).x) - B.ORIGIN[0], K.ToMM(o.CPoint(j).y) - B.ORIGIN[1]) for j in range(o.PointCount())]
        if len(pts) >= 3:
            out.append(shapely.Polygon(pts).buffer(0))
    return unary_union(out) if out else shapely.Polygon()


def _xy(v):
    return (K.ToMM(v.x) - B.ORIGIN[0], K.ToMM(v.y) - B.ORIGIN[1])


def open_pairs(b):
    """[(net, pad_a, pad_b)]: for each net whose pads sit on more than one copper
    island (geometry, as checks/layout.py sees it), the closest pad pair between
    the island of its first pad and the others."""
    import os
    import sys
    sys.path.insert(0, os.path.join(B.BOARD_DIR, "checks"))
    import layout as LC
    bd = LC.Board(b, LC.Netlist.load(B.NETLIST))
    _, find = LC.copper_islands(bd)
    out = []
    for net in sorted(bd.nl.nets):
        # physical pads: a part may repeat a number (a switch's 1, 1, 2, 2), and
        # each copy needs copper of its own
        phys = sorted(((r, p.GetNumber(), p) for r, fp in bd.fps.items() for p in fp.Pads()
                       if (r, p.GetNumber()) in bd.nl.nets[net] and p.GetAttribute() != K.PAD_ATTRIB_NPTH),
                      key=lambda t: (t[0], t[1], _xy(t[2].GetPosition())))
        isl = [(find(("pad", r, n, tuple(round(v, 3) for v in LC.xy(p.GetPosition())))), p) for r, n, p in phys]
        if len({i for i, _ in isl}) < 2:
            continue
        first = isl[0][0]
        tracks = [(find(("trk", i)), t) for i, t in enumerate(b.GetTracks()) if t.GetNetname() == net]
        a_items = [p for i, p in isl if i == first] + [t for i, t in tracks if i == first]
        b_items = [p for i, p in isl if i != first] + [t for i, t in tracks if i != first]
        out.append((net, a_items, b_items))
    return out


class Grid:
    """Per-layer label grids: 0 free, a net code where only that net's copper
    (grown by clearance + half width) reaches, -1 where two nets or the edge do."""

    def __init__(self, b, width, pair_lines):
        self.nx, self.ny = int(B.W / GRID) + 1, int(B.H / GRID) + 1
        clear = max(c for _, c, _ in B.NET_CLASSES.values())
        grow = clear + width / 2 + 0.01
        self.grow = grow
        self.label = {}
        for lay in LAYERS3:
            lab = np.zeros((self.nx, self.ny), dtype=np.int32)
            items = []
            for fp in b.GetFootprints():
                for p in fp.Pads():
                    if p.IsOnLayer(lay):
                        items.append((p.GetNetCode() or -2, _poly(p, lay)))
            for t in b.GetTracks():
                if t.IsOnLayer(lay):
                    items.append((t.GetNetCode() or -2, _poly(t, lay)))
            for code, g in items:
                g = g.buffer(grow)
                if g.is_empty:
                    continue
                x0, y0, x1, y1 = g.bounds
                i0, j0 = max(0, int(x0 / GRID)), max(0, int(y0 / GRID))
                i1, j1 = min(self.nx, int(x1 / GRID) + 2), min(self.ny, int(y1 / GRID) + 2)
                X, Y = np.meshgrid(np.arange(i0, i1) * GRID, np.arange(j0, j1) * GRID, indexing="ij")
                m = shapely.contains_xy(g, X, Y)
                win = lab[i0:i1, j0:j1]
                win[m & (win == 0)] = code
                win[m & (win != code) & (win != 0)] = -1
            X, Y = np.meshgrid(np.arange(self.nx) * GRID, np.arange(self.ny) * GRID, indexing="ij")
            edge = box(0, 0, B.W, B.H).buffer(-(B.JLC["copper_edge"] + width / 2 + 0.01))
            lab[~shapely.contains_xy(edge, X, Y)] = -1
            self.label[lay] = lab
        # where a via may go: clear of holes (hole-to-hole) and of the pairs' via keepout
        vr = B.JLC["via_diameter"] / 2
        holes = []
        for fp in b.GetFootprints():
            for p in fp.Pads():
                if p.GetAttribute() in (K.PAD_ATTRIB_PTH, K.PAD_ATTRIB_NPTH):
                    holes.append(Point(_xy(p.GetPosition())).buffer(
                        K.ToMM(p.GetDrillSize().x) / 2 + B.JLC["hole_to_hole"] + B.JLC["via_drill"] / 2))
        for t in b.GetTracks():
            if t.GetClass() == "PCB_VIA":
                holes.append(Point(_xy(t.GetPosition())).buffer(B.JLC["via_drill"] + B.JLC["hole_to_hole"]))
        keep = unary_union(pair_lines).buffer(B.CAN_W / 2 + B.REF_MARGIN + 0.25 + vr + 0.01) if pair_lines else shapely.Polygon()
        import routes
        keep_rects = [box(x0, y0, x1, y1).buffer(vr) for x0, y0, x1, y1 in routes.VIA_KEEPOUT]
        self.via_free = ~shapely.contains_xy(unary_union(holes + [keep] + keep_rects), X, Y)
        self.via_r = int(math.ceil((vr - width / 2) / GRID))

    def mark(self, code, lay, g, grow):
        g = g.buffer(grow)
        x0, y0, x1, y1 = g.bounds
        i0, j0 = max(0, int(x0 / GRID)), max(0, int(y0 / GRID))
        i1, j1 = min(self.nx, int(x1 / GRID) + 2), min(self.ny, int(y1 / GRID) + 2)
        if i1 <= i0 or j1 <= j0:
            return
        X, Y = np.meshgrid(np.arange(i0, i1) * GRID, np.arange(j0, j1) * GRID, indexing="ij")
        m = shapely.contains_xy(g, X, Y)
        win = self.label[lay][i0:i1, j0:j1]
        win[m & (win == 0)] = code
        win[m & (win != code) & (win != 0)] = -1

    def for_net(self, code):
        free = {lay: (self.label[lay] == 0) | (self.label[lay] == code) for lay in LAYERS3}
        from numpy.lib.stride_tricks import sliding_window_view as swv
        r = self.via_r
        both = np.pad(free[K.F_Cu] & free[K.B_Cu] & free[K.In2_Cu], r, constant_values=False)
        via_ok = self.via_free & swv(both, (2 * r + 1, 2 * r + 1)).all(axis=(2, 3))
        return free, via_ok


MAX_EXPAND = 4_000_000
MARGIN = 8.0         # mm: a search stays inside the start/goal box grown by this
PREROUTE_MARGIN = 14.0  # mm: pre-routes may go around a header's end (J2.10/12 face the edge)
IN2_COST = 4.0       # an In2 (power plane) step costs this many outer-layer steps


def astar(free, via_ok, starts, goals, layers=2, max_expand=None, margin=MARGIN):
    """starts/goals: {(layer_index, i, j)}; layer indices into LAYERS3 (F, B, In2),
    the first `layers` of them usable. Returns the cell path, or None when the
    goal is unreachable or the expansion / wall-time cap is hit."""
    import time
    t0 = time.monotonic()
    moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
             (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]
    gl = sorted(goals)
    gl = gl[::max(1, len(gl) // 64)]   # a deterministic sample: a cheap, near-admissible estimate
    cells = list(starts | goals)
    m = int(margin / GRID)
    nx, ny = via_ok.shape
    lo_i, hi_i = max(0, min(c[1] for c in cells) - m), min(nx, max(c[1] for c in cells) + m)
    lo_j, hi_j = max(0, min(c[2] for c in cells) - m), min(ny, max(c[2] for c in cells) + m)

    def h(n):
        return min(math.hypot(n[1] - q[1], n[2] - q[2]) for q in gl) * GRID

    pq, best, prev = [], {}, {}
    for st in sorted(starts):
        best[(st, (0, 0))] = 0.0
        heapq.heappush(pq, (h(st), 0.0, st, (0, 0)))
    expanded = 0
    while pq:
        f, d, n, md = heapq.heappop(pq)
        if n in goals:
            path = [n]
            k = (n, md)
            while k in prev:
                k = prev[k]
                path.append(k[0])
            return path[::-1]
        if d > best.get((n, md), 1e18) + 1e-9:
            continue
        expanded += 1
        # expansions, not wall time: a time cap made the result depend on the machine
        if expanded > (max_expand or MAX_EXPAND):
            print(f"  astar: cap hit after {expanded} expansions, {time.monotonic() - t0:.0f} s")
            return None
        L, i, j = n
        lay = LAYERS3[L]
        step = GRID * (IN2_COST if L == 2 else 1.0)
        for di, dj, c in moves:
            ni, nj = i + di, j + dj
            if not (lo_i <= ni < hi_i and lo_j <= nj < hi_j) or not free[lay][ni, nj]:
                continue
            nd = d + c * step + (TURN_COST * GRID * 10 if md not in ((0, 0), (di, dj)) else 0)
            key = ((L, ni, nj), (di, dj))
            if nd < best.get(key, 1e18) - 1e-12:
                best[key] = nd
                prev[key] = (n, md)
                heapq.heappush(pq, (nd + h((L, ni, nj)), nd, (L, ni, nj), (di, dj)))
        if via_ok[i, j]:
            for o in range(layers):
                if o == L or not free[LAYERS3[o]][i, j]:
                    continue
                nd = d + VIA_COST
                key = ((o, i, j), (0, 0))
                if nd < best.get(key, 1e18) - 1e-12:
                    best[key] = nd
                    prev[key] = (n, md)
                    heapq.heappush(pq, (nd + h((o, i, j)), nd, (o, i, j), (0, 0)))
    print(f"  astar: no path ({expanded} expansions, {time.monotonic() - t0:.0f} s)")
    return None


def pad_cells(shape, pad, lay_idx):
    """Grid cells inside a pad, track or via on one layer, as start/goal set."""
    lay = LAYERS3[lay_idx]
    if not pad.IsOnLayer(lay):
        return set()
    poly = _poly(pad, lay, -0.03)
    if poly.is_empty:
        return set()
    x0, y0, x1, y1 = poly.bounds
    out = set()
    for i in range(int(x0 / GRID), int(x1 / GRID) + 2):
        for j in range(int(y0 / GRID), int(y1 / GRID) + 2):
            if 0 <= i < shape[0] and 0 <= j < shape[1] and poly.contains(Point(i * GRID, j * GRID)):
                out.add((lay_idx, i, j))
    return out


def repair(b, add_track, add_via):
    """Route every open connection; returns (done, failed) lists of net names."""
    pair_nets = {n for p, q, _ in B.PAIRS.values() for n in (p, q)}
    pair_lines = [LineString([_xy(t.GetStart()), _xy(t.GetEnd())]) for t in b.GetTracks()
                  if t.GetClass() == "PCB_TRACK" and t.GetNetname() in pair_nets]
    done, failed = [], []
    grids = {}   # built once per track width; later repairs don't see earlier ones (few, far apart)
    for net, a_items, b_items in open_pairs(b):
        if net in pair_nets:
            failed.append(net)
            continue
        cls = B.net_class(net)
        width = max(B.NET_CLASSES[cls][0] * B.NECK, B.V12_W if cls == "12V" else B.JLC["track_min"])
        key = round(width, 3)
        if key not in grids:
            grids[key] = Grid(b, width, pair_lines)
        free, via_ok = grids[key].for_net(b.FindNet(net).GetNetCode())
        shape = via_ok.shape
        starts = set().union(*[pad_cells(shape, it, k) for it in a_items for k in (0, 1)])
        goals = set().union(*[pad_cells(shape, it, k) for it in b_items for k in (0, 1)])
        if not starts or not goals:
            failed.append(net)
            continue
        for L, i, j in starts | goals:
            free[LAYERS3[L]][i, j] = True
        path = astar(free, via_ok, starts, goals)
        if path is None:
            # last resort for a leftover: the In2 power plane as a third layer, at
            # IN2_COST per step so it is used only for short hops
            path = astar(free, via_ok, starts, goals, layers=3)
            if path is not None and _longest_run(path, 2) > B.IN2_HOP_MAX:
                path = None   # only short hops on the plane layer
        if path is None:
            failed.append(net)
            continue
        made = _emit(path, net, width, add_track, add_via)
        _mark_all(grids, made)
        done.append(net)
    return done, failed


def preroute(b, jobs, add_track, add_via):
    """Route (net, (ref, pad), (ref, pad)) jobs before freerouting runs: the
    nets whose pins are boxed in (the MCU's top row under CAN0) get their path
    while the board is still open. Copper of the net within 3 mm of an end pad
    (its fanout stub and via) counts as part of that end."""
    pair_nets = {n for p, q, _ in B.PAIRS.values() for n in (p, q)}
    pair_lines = [LineString([_xy(t.GetStart()), _xy(t.GetEnd())]) for t in b.GetTracks()
                  if t.GetClass() == "PCB_TRACK" and t.GetNetname() in pair_nets]
    fps = {fp.GetReference(): fp for fp in b.GetFootprints()}
    done, failed = [], []
    grids = {}
    for net, (ra, na), (rb, nb) in jobs:
        pa = next(p for p in fps[ra].Pads() if p.GetNumber() == na)
        pb = next(p for p in fps[rb].Pads() if p.GetNumber() == nb)
        cls = B.net_class(net)
        width = max(B.NET_CLASSES[cls][0] * B.NECK, B.V12_W if cls == "12V" else B.JLC["track_min"])
        key = round(width, 3)
        if key not in grids:
            grids[key] = Grid(b, width, pair_lines)
        free, via_ok = grids[key].for_net(b.FindNet(net).GetNetCode())
        shape = via_ok.shape

        def near(pad):
            c = _xy(pad.GetPosition())
            return [pad] + [t for t in b.GetTracks() if t.GetNetname() == net
                            and min(math.dist(c, _xy(t.GetStart())), math.dist(c, _xy(t.GetEnd()))) < 3.0]
        starts = set().union(*[pad_cells(shape, it, k) for it in near(pa) for k in (0, 1)])
        goals = set().union(*[pad_cells(shape, it, k) for it in near(pb) for k in (0, 1)])
        for L, i, j in starts | goals:
            free[LAYERS3[L]][i, j] = True
        path = astar(free, via_ok, starts, goals, max_expand=8_000_000,
                     margin=PREROUTE_MARGIN)   # board still open: long, wide searches are fine
        if path is None:
            failed.append(net)
            continue
        _mark_all(grids, _emit(path, net, width, add_track, add_via))
        done.append(net)
    return done, failed


def _longest_run(path, layer):
    """Longest stretch of a cell path on one layer, mm."""
    best = run = 0.0
    for a, c in zip(path, path[1:]):
        if a[0] == layer and c[0] == layer:
            run += math.hypot(c[1] - a[1], c[2] - a[2]) * GRID
            best = max(best, run)
        else:
            run = 0.0
    return best


def _mark_all(grids, made):
    """New copper becomes an obstacle in every grid (and vias block via spots)."""
    for gr in grids.values():
        X = Y = None
        for t in made:
            for lay in LAYERS3:
                if t.IsOnLayer(lay):
                    gr.mark(t.GetNetCode(), lay, _poly(t, lay), gr.grow)
            if t.GetClass() == "PCB_VIA":
                if X is None:
                    X, Y = np.meshgrid(np.arange(gr.nx) * GRID, np.arange(gr.ny) * GRID, indexing="ij")
                gr.via_free &= ~shapely.contains_xy(
                    Point(_xy(t.GetPosition())).buffer(B.JLC["via_drill"] + B.JLC["hole_to_hole"]), X, Y)


def _emit(path, net, width, add_track, add_via):
    """Lay the cell path down as tracks (runs merged) and vias; returns the items."""
    made = []
    _t, _v = add_track, add_via
    add_track = lambda *a: made.append(_t(*a))   # noqa: E731
    add_via = lambda *a: made.append(_v(*a))     # noqa: E731
    pts = [(L, i * GRID, j * GRID) for L, i, j in path]
    seg_start, last_dir = pts[0], None
    for k in range(1, len(pts)):
        a, c = pts[k - 1], pts[k]
        if a[0] != c[0]:
            if (seg_start[1], seg_start[2]) != (a[1], a[2]):
                add_track(net, width, (seg_start[1], seg_start[2]), (a[1], a[2]), LAYERS3[a[0]])
            add_via(net, (a[1], a[2]))
            seg_start, last_dir = c, None
            continue
        d = (round((c[1] - a[1]) / GRID), round((c[2] - a[2]) / GRID))
        if last_dir is not None and d != last_dir:
            add_track(net, width, (seg_start[1], seg_start[2]), (a[1], a[2]), LAYERS3[a[0]])
            seg_start = a
        last_dir = d
    end = pts[-1]
    if (seg_start[1], seg_start[2]) != (end[1], end[2]):
        add_track(net, width, (seg_start[1], seg_start[2]), (end[1], end[2]), LAYERS3[end[0]])
    return [m for m in made if m is not None]
