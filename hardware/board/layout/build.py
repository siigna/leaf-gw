"""Build the leaf-gw PCB from out/leaf_gw.net, deterministically.

    kicad-python build.py [--no-route]
    kicad-python build.py --silk-only   # redraw logo + silkscreen text on the saved board

Steps (each a function below):
  1. project + rules files (leaf_gw.kicad_pro, leaf_gw.kicad_dru)
  2. board: 4-layer JLC stack-up, outline, footprints from the netlist with
     their nets, placement (placement.py), mounting holes, silkscreen
  3. critical routes by script (routes.py): CAN pairs, USB pair, crystal,
     12 V input
  4. everything else by freerouting: DSN export, freerouting (single thread,
     fixed pass count), SES import
  5. zones (GND on In1, +3V3 on In2, GND pours on F/B), stitching vias, fill
  6. save leaf_gw.kicad_pcb (normalised: fixed UUIDs, no timestamps)

Run inside `nix develop .#hardware` (kicad-python = python3 with pcbnew).
"""

import functools
import json
import os
import re
import subprocess
import sys
import uuid

import pcbnew as K

import board as B
import logo
import placement
import routes

sys.path.insert(0, os.path.join(B.BOARD_DIR, "checks"))
from netlist import Netlist  # noqa: E402

print = functools.partial(print, flush=True)   # progress lines reach a log as they happen
FP_LIB = os.environ.get("KICAD9_FOOTPRINT_DIR", "")
LOCAL_LIB = os.path.join(B.BOARD_DIR, "footprints")


def mm(v):
    return K.FromMM(v)


def pt(x, y):
    """Board mm -> KiCad internal units, with the sheet origin offset."""
    return K.VECTOR2I(mm(B.ORIGIN[0] + x), mm(B.ORIGIN[1] + y))


def to_board(v):
    return (round(K.ToMM(v.x) - B.ORIGIN[0], 4), round(K.ToMM(v.y) - B.ORIGIN[1], 4))


# --- 1. project and rules --------------------------------------------------------

def write_project(path):
    classes = []
    for name, (width, clearance, _) in B.NET_CLASSES.items():
        classes.append({
            "name": name, "clearance": clearance, "track_width": width,
            "via_diameter": B.JLC["via_diameter"], "via_drill": B.JLC["via_drill"],
            "microvia_diameter": 0.3, "microvia_drill": 0.1,
            "diff_pair_width": B.CAN_W if name == "CAN" else B.USB_W if name == "USB" else width,
            "diff_pair_gap": B.CAN_GAP if name == "CAN" else B.USB_GAP if name == "USB" else 0.25,
            "diff_pair_via_gap": 0.25, "wire_width": 6, "bus_width": 12, "line_style": 0,
            "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
            "priority": 2147483647 if name == "Default" else len(classes),
        })
    patterns = [{"netclass": name, "pattern": net}
                for name, (_, _, nets) in B.NET_CLASSES.items() for net in nets]
    j = B.JLC
    pro = {
        "board": {
            "design_settings": {
                "defaults": {"board_outline_line_width": 0.05, "copper_line_width": 0.2,
                             "silk_line_width": 0.15, "silk_text_size_h": 1.0, "silk_text_size_v": 1.0,
                             "silk_text_thickness": 0.15},
                "rules": {
                    "min_clearance": j["clearance_min"], "min_track_width": j["track_min"],
                    "min_connection": j["track_min"], "min_via_diameter": j["via_diameter"],
                    "min_via_annular_width": j["via_ring_min"], "min_through_hole_diameter": j["hole_min"],
                    "min_hole_to_hole": j["hole_to_hole"], "min_hole_clearance": j["hole_clearance"],
                    "min_copper_edge_clearance": j["copper_edge"], "min_silk_clearance": j["silk_to_pad"],
                    "min_text_height": j["silk_text_min"], "min_text_thickness": j["silk_width_min"],
                    "solder_mask_to_copper_clearance": 0.0, "min_groove_width": 0.0,
                    "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "min_resolved_spokes": 1,
                    "max_error": 0.005, "allow_blind_buried_vias": False, "allow_microvias": False,
                    "use_height_for_length_calcs": True,
                },
                "rule_severities": {
                    # SKiDL writes no schematic, so there is nothing to compare against;
                    # parity is checked by checks/layout.py against the netlist instead.
                    "footprint_symbol_mismatch": "ignore", "missing_footprint": "ignore",
                    "extra_footprint": "ignore", "duplicate_footprints": "error",
                    "net_conflict": "ignore", "schematic_parity": "ignore",
                    "lib_footprint_issues": "ignore", "lib_footprint_mismatch": "ignore",
                },
                "track_widths": [0.0, B.SIGNAL_W, B.CAN_W, B.USB_W, B.POWER_W, B.V12_W],
                "via_dimensions": [{"diameter": 0.0, "drill": 0.0},
                                   {"diameter": j["via_diameter"], "drill": j["via_drill"]}],
                "diff_pair_dimensions": [{"gap": 0.0, "via_gap": 0.0, "width": 0.0},
                                         {"gap": B.CAN_GAP, "via_gap": 0.25, "width": B.CAN_W},
                                         {"gap": B.USB_GAP, "via_gap": 0.25, "width": B.USB_W}],
            },
        },
        "meta": {"filename": "leaf_gw.kicad_pro", "version": 3},
        "net_settings": {"classes": classes, "meta": {"version": 4}, "netclass_patterns": patterns},
    }
    with open(path, "w") as fh:
        json.dump(pro, fh, indent=2, sort_keys=True)
        fh.write("\n")


DRU = """(version 1)
# leaf-gw custom DRC rules (JLCPCB, SPEC.md "PCB"). Board-wide minimums are in
# leaf_gw.kicad_pro; these add what the net classes can't say.

(rule "12 V input tracks at least 0.5 mm"
  (condition "A.NetClass == '12V' && A.Type == 'track'")
  (constraint track_width (min {v12}mm)))

(rule "silkscreen at least 0.15 mm"
  (layer "?.Silkscreen")
  (constraint text_thickness (min {silk}mm)))

(rule "via drill and ring (JLC)"
  (condition "A.Type == 'via'")
  (constraint hole_size (min {drill}mm))
  (constraint annular_width (min {ring}mm)))
"""


def write_rules(path):
    j = B.JLC
    with open(path, "w") as fh:
        fh.write(DRU.format(v12=B.V12_W, silk=j["silk_width_min"], drill=j["via_drill"], ring=j["via_ring_min"]))


# --- 2. board ---------------------------------------------------------------------

def load_footprint(lib_nick, name):
    d = os.path.join(LOCAL_LIB if lib_nick == "leaf_gw" else FP_LIB, lib_nick + ".pretty")
    fp = K.FootprintLoad(d, name)
    if fp is None:
        raise SystemExit(f"footprint {lib_nick}:{name} not found in {d}")
    fp.SetFPID(K.LIB_ID(lib_nick, name))
    return fp


def outline(b):
    w, h, r = B.W, B.H, B.CORNER
    segs = [((r, 0), (w - r, 0)), ((w, r), (w, h - r)), ((w - r, h), (r, h)), ((0, h - r), (0, r))]
    for a, c in segs:
        s = K.PCB_SHAPE(b, K.SHAPE_T_SEGMENT)
        s.SetStart(pt(*a))
        s.SetEnd(pt(*c))
        s.SetLayer(K.Edge_Cuts)
        s.SetWidth(mm(0.05))
        b.Add(s)
    k = r * (1 - 0.5 ** 0.5)
    for s0, m, e in (((0, r), (k, k), (r, 0)), ((w - r, 0), (w - k, k), (w, r)),
                     ((w, h - r), (w - k, h - k), (w - r, h)), ((r, h), (k, h - k), (0, h - r))):
        a = K.PCB_SHAPE(b, K.SHAPE_T_ARC)
        a.SetArcGeometry(pt(*s0), pt(*m), pt(*e))
        a.SetLayer(K.Edge_Cuts)
        a.SetWidth(mm(0.05))
        b.Add(a)


def populate(b, nl):
    """Footprints from the netlist, in sorted order, with fields and pad nets."""
    nets = {}
    for name in sorted(nl.nets):
        ni = K.NETINFO_ITEM(b, name)
        b.Add(ni)
        nets[name] = ni
    pin_net = {(r, p): n for n, nodes in nl.nets.items() for r, p in nodes}
    fps = {}
    spare_x = 0.0
    for ref in sorted(nl.comps, key=natural):
        c = nl.comps[ref]
        lib, name = c["footprint"].split(":")
        fp = load_footprint(lib, name)
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        for k in ("LCSC", "MPN", "Manufacturer", "JLC"):
            if c["fields"].get(k):
                fp.SetField(k, c["fields"][k])
                f = fp.GetField(k)
                f.SetVisible(False)
                f.SetLayer(K.F_Fab)
        # silkscreen carries no designators (no room at this density); they stay on F.Fab
        fp.Reference().SetLayer(K.F_Fab)
        fp.SetPath(K.KIID_PATH("/" + c["fields"].get("SKiDL Tag", ref)))
        if ref not in placement.P and os.environ.get("LGW_PLACED_ONLY"):
            continue
        x, y, rot = placement.P.get(ref, (spare_x, B.H + 8, 0))
        if ref not in placement.P:
            spare_x += 6
        fp.SetPosition(pt(x, y))
        fp.SetOrientationDegrees(rot)
        b.Add(fp)
        for pad in fp.Pads():
            n = pin_net.get((ref, pad.GetNumber()))
            if n:
                pad.SetNet(nets[n])
        fps[ref] = fp
    return fps, nets


def natural(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


BOARD_ONLY = {  # footprints on the board that are not in the netlist
    "H1": ("MountingHole", "MountingHole_2.2mm_M2"),
    "H2": ("MountingHole", "MountingHole_2.2mm_M2"),
}


def board_only(b):
    for ref, (lib, name) in BOARD_ONLY.items():
        fp = load_footprint(lib, name)
        fp.SetReference(ref)
        fp.SetValue("M2")
        fp.Reference().SetLayer(K.F_Fab)
        x, y, rot = placement.P[ref]
        fp.SetPosition(pt(x, y))
        fp.SetOrientationDegrees(rot)
        fp.SetAttributes(fp.GetAttributes() | K.FP_BOARD_ONLY | K.FP_EXCLUDE_FROM_BOM | K.FP_EXCLUDE_FROM_POS_FILES)
        b.Add(fp)


def pad_lookup(fps):
    def pad(ref, num):
        for p in fps[ref].Pads():
            if p.GetNumber() == num:
                return to_board(p.GetPosition())
        raise KeyError(f"{ref}.{num}")
    return pad


def add_track(b, nets, net, w, a, c, layer=K.F_Cu):
    t = K.PCB_TRACK(b)
    t.SetStart(pt(*a))
    t.SetEnd(pt(*c))
    t.SetWidth(mm(w))
    t.SetLayer(layer)
    t.SetNet(nets[net])
    t.SetLocked(True)
    b.Add(t)
    return t


def split_at_junctions(segs):
    """Split each segment wherever another segment of the same net ends on it, so
    every T-junction is a shared endpoint (Specctra only joins wires at ends)."""
    out = []
    for net, w, a, c in segs:
        cuts = []
        for n2, _, a2, c2 in segs:
            if n2 != net:
                continue
            for p in (a2, c2):
                if p in (a, c):
                    continue
                dx, dy = c[0] - a[0], c[1] - a[1]
                L2 = dx * dx + dy * dy
                t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2
                if 0 < t < 1:
                    qx, qy = a[0] + t * dx, a[1] + t * dy
                    if (qx - p[0]) ** 2 + (qy - p[1]) ** 2 < 1e-8:
                        cuts.append((t, p))
        pts = [a] + [p for _, p in sorted(set(cuts))] + [c]
        out += [(net, w, p, q) for p, q in zip(pts, pts[1:]) if p != q]
    return out


def critical(b, fps, nets):
    segs = [(net, w, a, c) for net, w, pts in routes.lines(pad_lookup(fps))
            for a, c in zip(pts, pts[1:]) if a != c]
    for net, w, a, c in split_at_junctions(segs):
        add_track(b, nets, net, w, a, c)
    pad = pad_lookup(fps)
    layer = {"F": K.F_Cu, "B": K.B_Cu, "In2": K.In2_Cu}
    tracks, pt_vias = routes.passthrough(pad)
    def net_of(ref, num):
        return next(p.GetNetname() for p in fps[ref].Pads() if p.GetNumber() == num)
    for net, w, lay, pts in tracks + routes.local_links(pad, net_of):
        for a, c in zip(pts, pts[1:]):
            add_track(b, nets, net, w, a, c, layer[lay])
    for net, pos in pt_vias:
        v = K.PCB_VIA(b)
        v.SetPosition(pt(*pos))
        v.SetWidth(mm(B.JLC["via_diameter"]))
        v.SetDrill(mm(B.JLC["via_drill"]))
        v.SetNet(nets[net])
        v.SetLocked(True)
        b.Add(v)
    ref, nums = routes.PT_IN2_CLEAR
    for p in fps[ref].Pads():
        if p.GetNumber() in nums:
            p.SetRemoveUnconnected(True)    # no inner rings: the In2 hops pass between the holes
            p.SetKeepTopBottom(True)
    for net, pos in routes.vias(pad):
        v = K.PCB_VIA(b)
        v.SetPosition(pt(*pos))
        v.SetWidth(mm(B.JLC["via_diameter"]))
        v.SetDrill(mm(B.JLC["via_drill"]))
        v.SetNet(nets[net])
        v.SetLocked(True)
        b.Add(v)
        if net == "VBUS":
            p = [q for q in fps["U9"].Pads() if q.GetNetname() == net][0]
            add_track(b, nets, net, B.POWER_W, to_board(p.GetPosition()), pos)


def zone(b, nets, net, layer, priority, clearance=0.25, keep_out_holes=True):
    z = K.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(nets[net])
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(mm(clearance))
    z.SetMinThickness(mm(0.2))
    z.SetPadConnection(K.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(mm(0.25))
    z.SetThermalReliefSpokeWidth(mm(0.3))
    z.SetIslandRemovalMode(K.ISLAND_REMOVAL_MODE_ALWAYS)
    e = 0.0  # the outline follows the board edge; the edge clearance rule keeps copper 0.3 mm in
    o = z.Outline()
    o.NewOutline()
    for x, y in ((e, e), (B.W - e, e), (B.W - e, B.H - e), (e, B.H - e)):
        o.Append(mm(B.ORIGIN[0] + x), mm(B.ORIGIN[1] + y))
    z.SetZoneName(f"{net} {K.LayerName(layer) if hasattr(K, 'LayerName') else layer}")
    b.Add(z)
    return z


def planes(b, nets):
    """In1 = GND, In2 = +3V3, both solid; F/B get GND pours after routing."""
    zone(b, nets, "GND", K.In1_Cu, 0)
    zone(b, nets, "+3V3", K.In2_Cu, 0)


def pours(b, nets):
    zone(b, nets, "GND", K.F_Cu, 0)
    zone(b, nets, "GND", K.B_Cu, 0)


def fill(b):
    K.ZONE_FILLER(b).Fill(b.Zones())


DSN_LAYER_FIX = re.compile(r"\(layer (In[12]\.Cu)\s*\(type signal\)")


def quiet_zone(b):
    """Under the buck's switch node and L1 (checks/layout.py check_switch_node_clear):
    L1's courtyard and the BUCK_SW copper, grown by SW_QUIET, board mm."""
    from shapely.ops import unary_union
    g = [courtyard(fp, K.F_CrtYd) for fp in b.GetFootprints() if fp.GetReference() == "L1"]
    g += [poly_of(p, K.F_Cu) for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetname() == "BUCK_SW"]
    g += [poly_of(t, K.F_Cu) for t in b.GetTracks() if t.GetNetname() == "BUCK_SW"]
    return unary_union(g).buffer(B.SW_QUIET)


BUCK_GROUP = ("U7", "D8", "L1", "C24", "C25", "C26", "C27", "C28", "C29", "C30", "R13", "R14", "R15")


def buck_zone(b):
    """The buck group's courtyards: all its copper is scripted (routes.POWER_LINKS)
    or fanout, so the routers stay out; +5V_IGN leaves through TP8."""
    from shapely.ops import unary_union
    return unary_union([courtyard(fp, K.F_CrtYd) for fp in b.GetFootprints() if fp.GetReference() in BUCK_GROUP])


def dsn_prepare(text, quiet=None, closed=None):
    """Make the DSN say what we mean:
      - In1/In2 are planes: power layers, reached by vias, never routed on;
      - the differential pairs are finished: their nets leave the network (so
        freerouting can't add copper to them) and their wires become keepouts
        grown by the class clearance (so nothing else comes near them)."""
    text, n = DSN_LAYER_FIX.subn(r"(layer \1 (type power)", text)
    if n != 2:
        raise SystemExit(f"expected two inner layers in the DSN, patched {n}")
    # no via in an SMD pad (checks/layout.py check_via_pads)
    text, n = re.subn(r"\n  \(structure\n", "\n  (structure\n    (control (via_at_smd off))\n", text, count=1)
    if n != 1:
        raise SystemExit("DSN: no structure section")
    pair_nets = {net for p, q, _ in B.PAIRS.values() for net in (p, q)} | set(PLANE_NETS)
    keep = []
    from shapely.geometry import Point
    from shapely.ops import unary_union
    fixed_vias = unary_union([Point(int(m.group(1)), int(m.group(2))).buffer(600) for m in
                              re.finditer(r'\(via "[^"]+"\s+(-?\d+) (-?\d+)\s*\(net (\S+)\)', text)
                              if m.group(3) not in pair_nets])
    for m in re.finditer(r"\(wire \(path (\S+) (\d+)\s+([-\d\s]+)\)\(net (\S+)\)\(type \w+\)\)\n?", text):
        layer, width, coords, net = m.group(1), int(m.group(2)), m.group(3).split(), m.group(4)
        if net not in pair_nets:
            continue
        pts = [(int(coords[i]), int(coords[i + 1])) for i in range(0, len(coords), 2)]
        from shapely.geometry import LineString
        g = LineString(pts).buffer(width / 2 + 150, cap_style="round", quad_segs=4)
        ring = " ".join(f"{int(round(x))} {int(round(y))}" for x, y in g.exterior.coords)
        keep.append(f'    (keepout "" (polygon {layer} 0 {ring}))\n')
        if net not in PLANE_NETS:
            # no via near a pair: its In1 antipad would open the GND plane under it
            # (checks/layout.py wants In1 solid for 2 x prepreg beyond the track edge).
            # Our own fixed vias (fanout, VBUS) are cut out so they don't read as violations.
            r = (B.CAN_W / 2 + B.REF_MARGIN + 0.25) * 1000
            g = LineString(pts).buffer(r, cap_style="round", quad_segs=4).difference(fixed_vias)
            if g.is_empty:
                continue
            for part in getattr(g, "geoms", [g]):
                ring = " ".join(f"{int(round(x))} {int(round(y))}" for x, y in part.exterior.coords)
                for lay in ("F.Cu", "B.Cu"):
                    keep.append(f'    (via_keepout "" (polygon {lay} 0 {ring}))\n')
    for m in re.finditer(r'\(via "[^"]+"\s+(-?\d+) (-?\d+)\s*\(net (\S+)\)\(type \w+\)\)', text):
        if m.group(3) in pair_nets:
            x, y = int(m.group(1)), int(m.group(2))
            for layer in ("F.Cu", "B.Cu"):
                keep.append(f'    (keepout "" (circle {layer} {int(B.JLC["via_diameter"] * 1000 + 300)} {x} {y}))\n')
    text = re.sub(r'\(via "[^"]+"\s+-?\d+ -?\d+\s*\(net (\S+)\)\(type \w+\)\)\n?',
                  lambda m: "" if m.group(1) in pair_nets else m.group(0), text)
    text = re.sub(r"\(wire \(path \S+ \d+\s+[-\d\s]+\)\(net (\S+)\)\(type \w+\)\)\n?",
                  lambda m: "" if m.group(1) in pair_nets else m.group(0), text)
    for net in pair_nets:
        text, k = re.subn(r"\(net " + re.escape(net) + r"\s*\(pins[^)]*\)\s*\)", "", text)
        if k != 1:
            raise SystemExit(f"{net}: expected one network entry, found {k}")
        text = re.sub(r"(?<=\s)" + re.escape(net) + r"(?=\s)", "", text, count=0) if False else text
    # class member lists: drop the pair nets
    def strip_class(m):
        toks = m.group(2).split()
        return m.group(1) + " ".join(t for t in toks if t not in pair_nets) + "\n"
    text = re.sub(r"(\(class \S+ )([^(]*)", strip_class, text)
    for x0, y0, x1, y1 in routes.VIA_KEEPOUT:
        ring = " ".join(f"{int(round((B.ORIGIN[0] + x) * 1000))} {int(round(-(B.ORIGIN[1] + y) * 1000))}"
                        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)))
        for lay in ("F.Cu", "B.Cu"):
            keep.append(f'    (via_keepout "" (polygon {lay} 0 {ring}))\n')
    if closed is not None:   # no routing at all in the buck group
        for part in getattr(closed, "geoms", [closed]):
            ring = " ".join(f"{int(round((B.ORIGIN[0] + x) * 1000))} {int(round(-(B.ORIGIN[1] + y) * 1000))}"
                            for x, y in part.exterior.coords)
            for lay in ("F.Cu", "B.Cu"):
                keep.append(f'    (keepout "" (polygon {lay} 0 {ring}))\n')
    if quiet is not None:   # nothing under the switch node and L1 on B.Cu
        for part in getattr(quiet, "geoms", [quiet]):
            ring = " ".join(f"{int(round((B.ORIGIN[0] + x) * 1000))} {int(round(-(B.ORIGIN[1] + y) * 1000))}"
                            for x, y in part.exterior.coords)
            keep.append(f'    (keepout "" (polygon B.Cu 0 {ring}))\n')
    text = text.replace("    (via ", "".join(keep) + "    (via ", 1)
    # vias freerouting adds use a padstack 0.1 mm wider than the real one, so
    # its via-to-via clearance (0.15) also keeps JLC's 0.5 mm hole-to-hole;
    # autoroute() shrinks them back after the import
    via = re.search(r'\(via "(Via\[0-3\]_600:300_um)"\)', text)
    if not via:
        raise SystemExit("DSN: no routing via padstack")
    stack = re.search(r'    \(padstack "' + re.escape(via.group(1)) + r'"\n(?:      .*\n)*?    \)\n', text).group(0)
    # sized so its clearance also holds against our fixed, normal-size vias:
    # centres >= d/2 + via_diameter/2 + clearance = drill + hole_to_hole
    d = int(round((2 * (B.JLC["via_drill"] + B.JLC["hole_to_hole"] - B.NET_CLASSES["Default"][1])
                   - B.JLC["via_diameter"]) * 1000))
    wide = stack.replace(via.group(1), ROUTE_VIA).replace(f"{int(B.JLC['via_diameter'] * 1000)})", f"{d})")
    text = text.replace(stack, stack + wide, 1).replace(via.group(0), f'(via "{ROUTE_VIA}")', 1)
    text = text.replace(f'(use_via "{via.group(1)}")', f'(use_via "{ROUTE_VIA}")')
    return text


ROUTE_VIA = "Via_route_700:300_um"


def autoroute(b, work, passes):
    """DSN -> freerouting -> SES, everything except the finished pairs."""
    dsn, ses = os.path.join(work, "leaf_gw.dsn"), os.path.join(work, "leaf_gw.ses")
    if not K.ExportSpecctraDSN(b, dsn):
        raise SystemExit("DSN export failed")
    with open(dsn) as fh:
        text = dsn_prepare(fh.read(), quiet_zone(b), buck_zone(b))
    with open(dsn, "w") as fh:
        fh.write(text)
    cmd = ["freerouting", "-de", dsn, "-do", ses, "-mp", str(passes), "-mt", "1", "--gui.enabled=false"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)   # freerouting wall-time cap
    with open(os.path.join(work, "freerouting.log"), "w") as fh:
        fh.write(r.stdout + r.stderr)
    if r.returncode != 0 or not os.path.exists(ses):
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("freerouting failed")
    if not K.ImportSpecctraSES(b, ses):
        raise SystemExit("SES import failed")
    for v in b.GetTracks():
        if v.GetClass() == "PCB_VIA" and not v.IsLocked():
            v.SetWidth(mm(B.JLC["via_diameter"]))
            v.SetDrill(mm(B.JLC["via_drill"]))


# --- after routing: twin vias on power layer changes, GND stitching ----------

POWER_VIA_NETS = tuple(B.NET_CLASSES["12V"][2])   # as checks/layout.py: the nets where one via is the weak link


class ViaSpots:
    """Where a new via of a net may go: its ring clear of other nets' copper on
    F.Cu and B.Cu, of every SMD pad (board.VIA_PAD_WEB), the board edge and
    routes.VIA_KEEPOUT; its hole clear of every other hole; and, unless it is
    GND, its In1 antipad off the pairs' reference plane (as fanout())."""

    def __init__(self, b):
        from shapely.geometry import LineString, Point, box
        from shapely.ops import unary_union
        from shapely.strtree import STRtree
        self.r = B.JLC["via_diameter"] / 2
        self.clear = 0.16
        self.items = {K.F_Cu: [], K.B_Cu: []}
        smd, self.holes, pairs = [], [], []
        pair_nets = {n for p, q, _ in B.PAIRS.values() for n in (p, q)}
        for fp in b.GetFootprints():
            for p in fp.Pads():
                for lay in self.items:
                    if p.IsOnLayer(lay):
                        self.items[lay].append((poly_of(p, lay), p.GetNetname()))
                if p.GetAttribute() == K.PAD_ATTRIB_SMD:
                    smd.append(poly_of(p, K.F_Cu if p.IsOnLayer(K.F_Cu) else K.B_Cu))
                elif p.GetDrillSize().x:
                    self.holes.append((to_board(p.GetPosition()), K.ToMM(p.GetDrillSize().x) / 2))
        for t in b.GetTracks():
            for lay in self.items:
                if t.IsOnLayer(lay):
                    self.items[lay].append((poly_of(t, lay), t.GetNetname()))
            if t.GetClass() == "PCB_VIA":
                self.holes.append((to_board(t.GetPosition()), K.ToMM(t.GetDrillValue()) / 2))
            elif t.GetNetname() in pair_nets:
                pairs.append(LineString([to_board(t.GetStart()), to_board(t.GetEnd())]))
        self.trees = {lay: STRtree([g for g, _ in v]) for lay, v in self.items.items()}
        self.smd = unary_union(smd)
        self.pairs = unary_union(pairs)
        self.edge = box(0, 0, B.W, B.H).buffer(-(B.JLC["copper_edge"] + self.r))
        self.keep = unary_union([box(*k).buffer(self.r) for k in routes.VIA_KEEPOUT])
        self.quiet = quiet_zone(b)   # under the switch node and L1: GND only on B.Cu
        self.added = []   # (layer, geom, net)
        self.Point, self.LineString = Point, LineString

    def _free(self, lay, g, net):
        for i in self.trees[lay].query(g.buffer(self.clear)):
            og, on = self.items[lay][i]
            if on != net and og.distance(g) < self.clear:
                return False
        return all(on == net or al != lay or og.distance(g) >= self.clear for al, og, on in self.added)

    def ok(self, q, net, links=()):
        """A via at q, plus [(layer, track geometry)] links of its net."""
        import math
        v = self.Point(q)
        if not self.edge.contains(v) or self.keep.contains(v) or self.smd.distance(v) < self.r + B.VIA_PAD_WEB:
            return False
        if net != "GND" and self.pairs.distance(v) < B.CAN_W / 2 + B.REF_MARGIN + self.r + 0.3:
            return False
        if any(math.dist(q, c) < rr + B.JLC["via_drill"] / 2 + B.JLC["hole_to_hole"] + 0.02 for c, rr in self.holes):
            return False
        disc = v.buffer(self.r)
        if net != "GND" and (disc.intersects(self.quiet) or any(lay == K.B_Cu and g.intersects(self.quiet) for lay, g in links)):
            return False
        return all(self._free(lay, disc, net) for lay in self.items) and all(self._free(lay, g, net) for lay, g in links)

    def take(self, b, nets, q, net, links=()):
        via = K.PCB_VIA(b)
        via.SetPosition(pt(*q))
        via.SetWidth(mm(B.JLC["via_diameter"]))
        via.SetDrill(mm(B.JLC["via_drill"]))
        via.SetNet(nets[net])
        b.Add(via)
        self.holes.append((q, B.JLC["via_drill"] / 2))
        disc = self.Point(q).buffer(self.r)
        self.added += [(lay, disc, net) for lay in self.items] + [(lay, g, net) for lay, g in links]
        return via


TWIN_REACH = 1.5     # mm: a power via's partner sits within this (checks/layout.py check_power_vias)


def twin_power_vias(b, nets):
    """Every layer change on a supply net gets a second via: a single 0.3 mm
    via is the weak link of a supply track. For each lone via on a 12 V net, the first clear spot 0.85 to 1.25 mm away (along its own tracks
    first) takes a twin, joined to it on both of its layers."""
    import math
    spots = ViaSpots(b)
    vias = sorted([t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() in POWER_VIA_NETS],
                  key=lambda v: (v.GetNetname(), to_board(v.GetPosition())))
    added, lone = 0, []
    for v in vias:
        net, q = v.GetNetname(), to_board(v.GetPosition())
        if any(o.GetNetname() == net and 0.001 < math.dist(q, to_board(o.GetPosition())) <= TWIN_REACH
               for o in b.GetTracks() if o.GetClass() == "PCB_VIA"):
            continue
        att = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net
               and min(math.dist(q, to_board(t.GetStart())), math.dist(q, to_board(t.GetEnd()))) < 0.01]
        lays = {t.GetLayer() for t in att}
        if not lays <= {K.F_Cu, K.B_Cu} or len(lays) < 2:
            continue    # the scripted In2 hops have their twins already; a via on one layer is dangling
        w = min(K.ToMM(t.GetWidth()) for t in att)
        dirs = []
        for t in att:   # along its tracks first
            a, c = to_board(t.GetStart()), to_board(t.GetEnd())
            o = c if math.dist(q, a) < 0.01 else a
            dirs.append(math.atan2(o[1] - q[1], o[0] - q[0]))
        dirs += [k * math.pi / 12 for k in range(24)]
        done = False
        dirs += [k * math.pi / 24 + math.pi / 48 for k in range(48)]
        for lw in (w, min(w, 0.3), 0.2):
          for d in (0.82, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.48):
            for ang in dirs:
                c = (round(q[0] + d * math.cos(ang), 3), round(q[1] + d * math.sin(ang), 3))
                link = spots.LineString([q, c]).buffer(lw / 2)
                if spots.ok(c, net, [(K.F_Cu, link), (K.B_Cu, link)]):
                    spots.take(b, nets, c, net, [(K.F_Cu, link), (K.B_Cu, link)])
                    for lay in (K.F_Cu, K.B_Cu):
                        t = add_track(b, nets, net, lw, q, c, lay)
                        t.SetLocked(False)
                    added += 1
                    done = True
                    break
            if done:
                break
          if done:
            break
        if not done:
            lone.append(f"{net} at {q}")
    for x in lone:
        print(f"  power via with no room for a twin: {x}")
    return added


STITCH_PITCH = 5.0    # mm along the board edge
STITCH_INSET = 1.0    # mm in from the edge


def stitch_gnd(b, nets):
    """GND stitching vias (call with the pours filled): along the board edge
    about every STITCH_PITCH where the F.Cu and B.Cu pours both reach, then
    into every outer-layer GND pour island that reaches In1 through fewer than
    two vias. An island that cannot take them is cut out of its pour (a rule
    area), so no copper is left hanging off a single via. Returns (edge vias,
    island vias, islands removed)."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    spots = ViaSpots(b)
    r = spots.r + 0.05

    def fill_of(lay):
        return unary_union([polyset(z.GetFilledPolysList(lay)) for z in b.Zones()
                            if z.GetNetname() == "GND" and z.IsOnLayer(lay) and not z.GetIsRuleArea()])
    f, bk = fill_of(K.F_Cu), fill_of(K.B_Cu)
    both = f.intersection(bk).buffer(-r)
    ring = box(0, 0, B.W, B.H).buffer(-STITCH_INSET).exterior
    import math
    n_edge, s, last = 0, 0.0, -1e9
    while s < ring.length:
        q = ring.interpolate(s)
        if s - last >= STITCH_PITCH:
            # the nearest spot to the inset point where both pours leave room (checks/layout.py
            # counts the edge as stitchable within 1.5 mm of such room)
            import numpy as np
            import shapely
            g = np.arange(-1.5, 1.501, 0.1)
            X, Y = np.meshgrid(q.x + g, q.y + g)
            m = (np.hypot(X - q.x, Y - q.y) <= 1.5) & shapely.contains_xy(both, X, Y)
            for c in sorted(zip(X[m].round(3), Y[m].round(3)), key=lambda c: (math.dist(c, (q.x, q.y)), c)):
                c = (float(c[0]), float(c[1]))
                if spots.ok(c, "GND"):
                    spots.take(b, nets, c, "GND")
                    n_edge += 1
                    last = s
                    break
        s += 0.25
    fill(b)
    n_isl, removed, kept = 0, 0, set()
    for _ in range(5):   # a via, a cut or a refill can reshape the islands next to it: until none is short
        cut, took_any = [], 0
        for lay in (K.F_Cu, K.B_Cu):
            for isl in getattr(fill_of(lay), "geoms", [fill_of(lay)]):
                have = stitches(b, isl)
                if have >= 2 or (lay, round(isl.area, 1), tuple(round(v) for v in isl.centroid.coords[0])) in kept:
                    continue
                region = isl.buffer(-r)
                cands = []
                if not region.is_empty:
                    x0, y0, x1, y1 = region.bounds
                    y = y0
                    while y <= y1:
                        x = x0
                        while x <= x1:
                            if region.contains(Point(x, y)):
                                cands.append((round(x, 3), round(y, 3)))
                            x += 0.25
                        y += 0.25
                took = []
                for c in cands:
                    if have + len(took) >= 2:
                        break
                    if all(Point(c).distance(Point(t)) >= 1.0 for t in took) and spots.ok(c, "GND"):
                        spots.take(b, nets, c, "GND")
                        took.append(c)
                n_isl += len(took)
                took_any += len(took)
                if have + len(took) < 2:
                    cut.append((lay, isl))
                if os.environ.get("LGW_DEBUG"):
                    c = isl.representative_point()
                    print(f"  island {K.LayerName(lay) if hasattr(K, 'LayerName') else lay} ({c.x:.2f}, {c.y:.2f}) {isl.area:.1f} mm2: "
                          f"{have} + {len(took)} of {len(cands)} spots")
        for lay, isl in cut:   # unless a pad hangs on that island alone
            b.BuildConnectivity()
            base = b.GetConnectivity().GetUnconnectedCount(True)
            z = keepout(b, lay, isl.buffer(0.05))
            fill(b)
            b.BuildConnectivity()
            if b.GetConnectivity().GetUnconnectedCount(True) > base:
                z.SetLayer(K.Dwgs_User)   # (Remove from Python corrupts later loads)
                z.SetIsRuleArea(False)
                b.Delete(z)
                fill(b)
                c = isl.representative_point()
                print(f"  GND island at ({c.x:.2f}, {c.y:.2f}) feeds a pad: kept with {stitches(b, isl)} via(s)")
                kept.add((lay, round(isl.area, 1), tuple(round(v) for v in isl.centroid.coords[0])))
            else:
                removed += 1
        fill(b)
        if not cut and not took_any:
            break
    return n_edge, n_isl, removed


def polyset(ps):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        holes = [[to_board(ps.Hole(i, k).CPoint(j)) for j in range(ps.Hole(i, k).PointCount())] for k in range(ps.HoleCount(i))]
        ext = [to_board(o.CPoint(j)) for j in range(o.PointCount())]
        if len(ext) >= 3:
            out.append(Polygon(ext, [h for h in holes if len(h) >= 3]).buffer(0))
    return unary_union(out)


def stitches(b, isl):
    """GND vias and In1-connected GND through-hole pads touching an island."""
    from shapely.geometry import Point
    n = sum(1 for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"
            and isl.distance(Point(to_board(t.GetPosition()))) < 0.05)
    n += sum(1 for fp in b.GetFootprints() for p in fp.Pads()
             if p.GetNetname() == "GND" and p.GetAttribute() == K.PAD_ATTRIB_PTH and p.FlashLayer(K.In1_Cu)
             and isl.distance(Point(to_board(p.GetPosition()))) < 0.05)
    return n


def keepout(b, lay, g):
    """A rule area on one layer over g: no zone fill there."""
    z = K.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    z.SetLayer(lay)
    o = z.Outline()
    o.NewOutline()
    ext = g.exterior if g.geom_type == "Polygon" else max(g.geoms, key=lambda p: p.area).exterior
    for x, y in list(ext.coords)[:-1]:
        o.Append(mm(B.ORIGIN[0] + x), mm(B.ORIGIN[1] + y))
    b.Add(z)
    return z


def logo_footprint(b, x, y):
    """The logo (logo.py: the leaf) as exposed copper: one custom-shape pad on
    F.Cu with no net, its solder-mask opening the same shape, so with an ENIG
    finish it reads as a gold leaf and the vein (a gap in the copper) stays
    under mask. Being a pad, every router and the zone fill keep clear of it."""
    from shapely.ops import unary_union
    fp = K.FOOTPRINT(b)
    fp.SetReference("LOGO")
    fp.Reference().SetVisible(False)
    fp.Reference().SetLayer(K.F_Fab)
    fp.SetValue("leaf logo")
    fp.Value().SetVisible(False)
    fp.Value().SetLayer(K.F_Fab)
    fp.SetFPID(K.LIB_ID("leaf_gw", "leaf_logo"))
    fp.SetAttributes(K.FP_BOARD_ONLY | K.FP_EXCLUDE_FROM_BOM | K.FP_EXCLUDE_FROM_POS_FILES)
    fp.SetPosition(pt(x, y))
    shape = unary_union(logo.polygons())
    anchor = shape.representative_point()   # the custom pad's anchor must lie on its copper
    pad = K.PAD(fp)
    pad.SetNumber("")
    pad.SetAttribute(K.PAD_ATTRIB_SMD)
    layers = K.LSET()
    layers.AddLayer(K.F_Cu)
    layers.AddLayer(K.F_Mask)    # no F.Paste: nothing is soldered here
    pad.SetLayerSet(layers)
    pad.SetShape(K.F_Cu, K.PAD_SHAPE_CUSTOM)
    pad.SetAnchorPadShape(K.F_Cu, K.PAD_SHAPE_CIRCLE)
    pad.SetSize(K.F_Cu, K.VECTOR2I(mm(0.3), mm(0.3)))
    pad.SetPosition(pt(x + anchor.x, y + anchor.y))
    pad.SetLocalSolderMaskMargin(mm(LOGO_MASK_MARGIN))
    for poly in getattr(shape, "geoms", [shape]):
        ps = K.SHAPE_POLY_SET()
        for k, ring in enumerate([poly.exterior] + list(poly.interiors)):
            if k == 0:
                ps.NewOutline()
            else:
                ps.NewHole()
            for px, py in list(ring.coords)[:-1]:
                ps.Append(mm(px - anchor.x), mm(py - anchor.y), -1, -1 if k == 0 else k - 1)
        pad.AddPrimitivePoly(K.F_Cu, ps, 0, True)
    fp.Add(pad)
    b.Add(fp)


# The mask overlaps the leaf's copper edge by this much, so JLC's mask
# registration (about 0.05 mm) can't show a sliver of bare substrate beside it.
LOGO_MASK_MARGIN = -0.05


def silk_text(b, text, x, y, size=1.0, width=None, layer=K.F_SilkS, rot=0, just="left", knockout=False):
    t = K.PCB_TEXT(b)
    t.SetIsKnockout(knockout)
    t.SetText(text)
    t.SetLayer(layer)
    t.SetTextSize(K.VECTOR2I(mm(width or size), mm(size)))
    t.SetTextThickness(mm(max(B.JLC["silk_width_min"], 0.15 * size)))
    t.SetVertJustify(K.GR_TEXT_V_ALIGN_CENTER)
    t.SetHorizJustify({"left": K.GR_TEXT_H_ALIGN_LEFT, "center": K.GR_TEXT_H_ALIGN_CENTER,
                       "right": K.GR_TEXT_H_ALIGN_RIGHT}[just])
    t.SetPosition(pt(x, y))
    t.SetTextAngleDegrees(rot)
    if layer == K.B_SilkS:
        t.SetMirrored(True)
    b.Add(t)
    return t


def silkscreen(b):
    """SPEC "Silkscreen branding" and "PCB": logo, name, revision, licence line,
    the bench warning, header pin-1 marks and bus names."""
    lx, ly = placement.LOGO
    logo_footprint(b, lx, ly)
    for text, (x, y, size, width, rot, just) in placement.SILK_TEXT.items():
        silk_text(b, text.replace("{rev}", B.REVISION), x, y, size, width, K.F_SilkS, rot, just,
                  text in placement.KNOCKOUT)
    for text, (x, y, size, width, rot, just) in placement.BACK_TEXT.items():
        silk_text(b, text.replace("{rev}", B.REVISION), x, y, size, width, K.B_SilkS, rot, just,
                  text in placement.KNOCKOUT)
    silk_shape(b, logo.esd_paw(), *placement.ESD_PAW, K.B_SilkS)
    qx, qy = placement.QR
    code = logo.qr()
    silk_shape(b, code, qx, qy, K.B_SilkS)
    silk_text(b, "github.com/siigna/leaf-gw", qx + code.bounds[2] / 2, qy + code.bounds[3] + 1.0,
              1.0, 0.7, K.B_SilkS, 0, "center")
    polarity_marks(b)
    labels(b)


POLARITY_BAR = 0.2   # mm, the cathode bar's width (JLC silkscreen minimum 0.15)


def polarized(fp):
    """Two-terminal diodes and LEDs: D<n> with pads 1 (cathode) and 2."""
    return re.fullmatch(r"D\d+", fp.GetReference()) and sorted(p.GetNumber() for p in fp.Pads()) == ["1", "2"]


def cathode_frame(fp):
    """(pad 1 centre, unit vector from pad 2 to pad 1, its normal, pad 1's mask
    reach along that vector, pad 1's half width across it), board mm."""
    import math
    p1, p2 = (next(p for p in fp.Pads() if p.GetNumber() == n) for n in ("1", "2"))
    c1, c2 = to_board(p1.GetPosition()), to_board(p2.GetPosition())
    d = math.dist(c1, c2)
    u = ((c1[0] - c2[0]) / d, (c1[1] - c2[1]) / d)
    v = (-u[1], u[0])
    m = poly_of(p1, K.F_Mask)
    pts = list(m.exterior.coords) if m.geom_type == "Polygon" else [q for g in m.geoms for q in g.exterior.coords]
    reach = max((x - c1[0]) * u[0] + (y - c1[1]) * u[1] for x, y in pts)
    half = max(abs((x - c1[0]) * v[0] + (y - c1[1]) * v[1]) for x, y in pts)
    return c1, u, v, reach, half


def polarity_marks(b):
    """A cathode bar on the top silkscreen beyond pad 1 of every diode and LED
    whose library mark silk_cleanup removed (checks/layout.py
    check_polarity_marks looks for the same thing): the full pad width, else
    shorter; clear of pad openings, other silkscreen and the board edge. A
    diode with no room for one stops the build."""
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    fps = list(b.GetFootprints())
    gap = B.JLC["silk_to_pad"] + 0.05
    inside = box(0, 0, B.W, B.H).buffer(-0.3)
    mask = unary_union([poly_of(p, K.F_Mask, gap) for fp in fps for p in fp.Pads() if p.IsOnLayer(K.F_Mask)])
    silk = [poly_of(d, K.F_SilkS) for d in b.GetDrawings() if d.GetLayer() == K.F_SilkS]
    silk += [poly_of(g, K.F_SilkS) for fp in fps for g in fp.GraphicalItems() if g.GetLayer() == K.F_SilkS]
    silk = unary_union(silk).buffer(LABEL_CLEAR)
    missing = []
    for fp in sorted(fps, key=lambda f: natural(f.GetReference())):
        if not polarized(fp) or has_cathode_mark(b, fp):
            continue
        c1, u, v, reach, half = cathode_frame(fp)
        for frac in (1.0, 0.75, 0.5):
            a = reach + gap + 0.02
            corners = [(a, -half * frac), (a + POLARITY_BAR, -half * frac), (a + POLARITY_BAR, half * frac), (a, half * frac)]
            g = Polygon([(c1[0] + s * u[0] + t * v[0], c1[1] + s * u[1] + t * v[1]) for s, t in corners])
            if inside.contains(g) and not g.intersects(mask) and not g.intersects(silk):
                silk_shape(b, g, 0, 0, K.F_SilkS)
                silk = silk.union(g.buffer(LABEL_CLEAR))
                break
        else:
            missing.append(fp.GetReference())
    if missing:
        raise SystemExit("no room for a cathode mark: " + ", ".join(missing))


def has_cathode_mark(b, fp):
    """Silkscreen across most of pad 1's width just beyond its outer edge."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    c1, u, v, reach, half = cathode_frame(fp)
    zone = Polygon([(c1[0] + s * u[0] + t * v[0], c1[1] + s * u[1] + t * v[1])
                    for s, t in ((reach, -half), (reach + MARK_REACH, -half), (reach + MARK_REACH, half), (reach, half))])
    items = [poly_of(g, K.F_SilkS) for g in fp.GraphicalItems() if g.GetLayer() == K.F_SilkS]
    items += [poly_of(d, K.F_SilkS) for d in b.GetDrawings() if d.GetLayer() == K.F_SilkS]
    hit = unary_union(items).intersection(zone)
    if hit.is_empty:
        return False
    pts = [q for g in getattr(hit, "geoms", [hit]) if hasattr(g, "exterior") for q in g.exterior.coords]
    span = [(x - c1[0]) * v[0] + (y - c1[1]) * v[1] for x, y in pts]
    return bool(span) and max(span) - min(span) >= MARK_SPAN * 2 * half


MARK_REACH = 1.0    # mm beyond pad 1's opening where the cathode mark must be
MARK_SPAN = 0.5     # ... across at least this fraction of the pad's width


def silk_shape(b, shape, x, y, layer):
    """A shapely shape (mm, origin top-left) as filled silkscreen polygons at
    board (x, y); on the back it is mirrored so it reads from that side."""
    w = shape.bounds[2]
    for poly in getattr(shape, "geoms", [shape]):
        s = K.PCB_SHAPE(b, K.SHAPE_T_POLY)
        s.SetLayer(layer)
        s.SetFilled(True)
        s.SetWidth(0)
        chain = K.SHAPE_LINE_CHAIN()
        for px, py in logo.keyholed(poly):
            px = w - px if layer == K.B_SilkS else px
            chain.Append(mm(B.ORIGIN[0] + x + px), mm(B.ORIGIN[1] + y + py))
        chain.SetClosed(True)
        ps = K.SHAPE_POLY_SET()
        ps.AddOutline(chain)
        s.SetPolyShape(ps)
        b.Add(s)


LABEL_GAP = 0.5     # mm, label to its part's courtyard (glyphs overshoot their nominal height)
LABEL_CLEAR = 0.25  # mm, label to any other silkscreen or courtyard
LABEL_RINGS = 3     # how far out a label may move from its part (1 mm a ring)


def labels(b):
    """placement.LABELS: each label goes to the first spot around its part's
    courtyard (above or below, centred then flush with its left edge; right,
    left; then turned 90 degrees on the sides; nearest ring first) that is clear of pad openings, courtyards, other silkscreen and the board
    edge. Deterministic; a label with no room stops the build."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    fps = {fp.GetReference(): fp for fp in b.GetFootprints()}
    gap = B.JLC["silk_to_pad"] + 0.05
    inside = box(0, 0, B.W, B.H).buffer(-0.4)
    avoid = {}
    for layer, mask_layer, crt in ((K.F_SilkS, K.F_Mask, K.F_CrtYd), (K.B_SilkS, K.B_Mask, K.B_CrtYd)):
        g = [poly_of(p, mask_layer, gap) for fp in fps.values() for p in fp.Pads() if p.IsOnLayer(mask_layer)]
        g += [poly_of(d, layer, LABEL_CLEAR) for d in b.GetDrawings() if d.GetLayer() == layer]
        for fp in fps.values():
            g += [poly_of(it, layer, LABEL_CLEAR) for it in fp.GraphicalItems() if it.GetLayer() == layer]
            c = courtyard(fp, crt)
            if not c.is_empty:
                g.append(c.buffer(LABEL_CLEAR))
        avoid[layer] = unary_union(g)
    missing = []
    for text, ref, side, size in placement.LABELS:
        layer = K.F_SilkS if side == "top" else K.B_SilkS
        crt = courtyard(fps[ref], K.B_CrtYd if side == "back" else K.F_CrtYd)
        if crt.is_empty:   # a top part labelled on the back: beside where it sits
            crt = courtyard(fps[ref], K.F_CrtYd)
        cx0, cy0, cx1, cy1 = crt.bounds
        mx, my = (cx0 + cx1) / 2, (cy0 + cy1) / 2
        spots = []
        for ring in range(LABEL_RINGS):   # nearest first, then 1 mm further out each ring
            g0 = LABEL_GAP + ring
            d = g0 + size / 2
            spots += [((mx, cy0 - d), 0, "center"), ((mx, cy1 + d), 0, "center"),
                      ((cx0 + LABEL_CLEAR, cy0 - d), 0, "left"), ((cx0 + LABEL_CLEAR, cy1 + d), 0, "left"),
                      ((cx1 + g0, my), 0, "left"), ((cx0 - g0, my), 0, "right"),
                      ((cx1 + d, my), 90, "center"), ((cx0 - d, my), 90, "center")]
        for (x, y), rot, just in spots:
            t = silk_text(b, text, x, y, size, 0.7 * size, layer, rot, just)
            g = poly_of(t, layer)
            if inside.contains(g) and not g.intersects(avoid[layer]):
                avoid[layer] = avoid[layer].union(g.buffer(LABEL_CLEAR))
                break
            b.Delete(t)
        else:
            missing.append(f"{text!r} ({ref}, {side})")
    if missing:
        msg = "silkscreen labels with no clear spot: " + ", ".join(missing)
        if os.environ.get("LGW_NO_PREROUTE"):   # dev: placement checks only
            print(msg)
        else:
            raise SystemExit(msg)


def courtyard(fp, layer):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    ps = fp.GetCourtyard(layer)
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        pts = [to_board(o.CPoint(j)) for j in range(o.PointCount())]
        if len(pts) >= 3:
            out.append(Polygon(pts).buffer(0))
    return unary_union(out)


PLANE_NETS = ("GND", "+3V3")


def poly_of(item, layer, grow=0.0):
    ps = K.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, mm(grow), mm(0.005), K.ERROR_OUTSIDE)
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        pts = [to_board(o.CPoint(j)) for j in range(o.PointCount())]
        if len(pts) >= 3:
            out.append(Polygon(pts).buffer(0))
    return unary_union(out)


def fanout(b, fps, nets):
    """A via to its plane next to every SMD pad on GND (In1) or +3V3 (In2).

    freerouting does not reach Specctra planes from SMD pads when the plane
    layers are closed to wiring, so the plane connections are made here,
    deterministically: candidate spots on rings around the pad, nearest first,
    preferring the side away from the part's centre; the first spot where the
    via and its stub clear every other net's copper (and keep a +3V3 antipad off
    the GND plane under the pairs) wins. A pad within reach of an existing via
    of its net shares it."""
    import math

    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    # clearance to other nets: plane vias 0.16; signal vias, which freerouting
    # must then reach, 0.32 (its 0.15 clearance on top of the 0.15 growth of the
    # keepouts it sees for the finished nets, or it reads them as violations)
    via_r, stub_w = B.JLC["via_diameter"] / 2, 0.3
    clear_of = lambda net: 0.16 if net in PLANE_NETS else 0.32
    obst = []   # (geom, net)
    for fp in fps.values():
        for p in fp.Pads():
            if p.IsOnLayer(K.F_Cu):
                obst.append((poly_of(p, K.F_Cu), "pad:" + p.GetNetname()))
            if p.GetAttribute() in (K.PAD_ATTRIB_PTH, K.PAD_ATTRIB_NPTH):
                obst.append((Point(to_board(p.GetPosition())).buffer(K.ToMM(p.GetDrillSize().x) / 2 + 0.25), "_hole"))
    pair_lines = []
    for t in b.GetTracks():
        g = poly_of(t, t.GetLayer()) if t.GetClass() == "PCB_TRACK" else poly_of(t, K.F_Cu)
        obst.append((g, t.GetNetname()))
        if t.GetNetname() in {n for p, q, _ in B.PAIRS.values() for n in (p, q)}:
            pair_lines.append(LineString([to_board(t.GetStart()), to_board(t.GetEnd())]))
    for d in b.GetDrawings():
        if d.GetLayer() == K.Edge_Cuts:
            pass
    pair_u = unary_union(pair_lines)
    # no via in or touching any SMD pad, its own net's included (board.VIA_PAD_WEB)
    smd_u = unary_union([poly_of(p, K.F_Cu) for fp in fps.values() for p in fp.Pads()
                         if p.GetAttribute() == K.PAD_ATTRIB_SMD and p.IsOnLayer(K.F_Cu)])
    edge = __import__("shapely.geometry", fromlist=["box"]).box(0, 0, B.W, B.H).buffer(-(B.JLC["copper_edge"] + via_r))
    vias = [(Point(to_board(t.GetPosition())), t.GetNetname()) for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
    added = []  # (geom, net) copper placed by this pass
    tree_geoms = [g for g, _ in obst]
    tree = STRtree(tree_geoms)

    finished = {n for p, q, _ in B.PAIRS.values() for n in (p, q)} | set(PLANE_NETS)

    def need(net, other):
        # a signal via freerouting must reach keeps 0.32 from tracks and vias that
        # become (0.15-grown) keepouts in the DSN; pads stay pads, 0.16 like the rest
        return 0.32 if net not in PLANE_NETS and other in finished else 0.16

    def free(geom, net):
        for i in tree.query(geom.buffer(0.32)):
            g, n = obst[i]
            if n.startswith("pad:"):
                if n[4:] != net and g.distance(geom) < 0.16:
                    return False
            elif n != net and g.distance(geom) < need(net, n):
                return False
        for g, n in added:
            if n != net and g.distance(geom) < max(need(net, n), need(n, net)):
                return False
        return True

    placed = 0
    # ICs first, so a decoupling cap can share its IC pin's via; then a second
    # round for the pads that found no room, which may now share a later via
    # signal pins first (they have nowhere else to go), then ICs before passives
    todo = [(ref, p) for ref in sorted(fps, key=lambda r: (-len(fps[r].Pads()), natural(r)))
            for p in sorted(fps[ref].Pads(), key=lambda q: (q.GetNetname() in PLANE_NETS, q.GetNumber()))
            if p.GetAttribute() == K.PAD_ATTRIB_SMD
            and (p.GetNetname() in PLANE_NETS or (ref, p.GetNumber()) in routes.FANOUT_SIGNALS)]
    todo.sort(key=lambda rp: rp[1].GetNetname() in PLANE_NETS)   # stable: keeps the order within each group
    for rnd in (0, 1):
      failed = []
      for ref, p in todo:
            fp = fps[ref]
            c = to_board(fp.GetPosition())
            net = p.GetNetname()
            q = to_board(p.GetPosition())
            # share a via of the same net within reach
            near = [v for v, n in vias if n == net and v.distance(Point(q)) <= 2.5 and net in PLANE_NETS]
            if near:
                v = min(near, key=lambda v: v.distance(Point(q)))
                stub = LineString([q, (v.x, v.y)]).buffer(stub_w / 2)
                if free(stub, net):
                    add_track(b, nets, net, stub_w, q, (v.x, v.y))
                    added.append((stub, net))
                    continue
            pad_g = poly_of(p, K.F_Cu)
            away = math.atan2(q[1] - c[1], q[0] - c[0]) if q != c else 0.0
            best = None
            r0 = max(0.0, pad_g.exterior.distance(Point(q)) if pad_g.geom_type == "Polygon" else 0.3)
            # anchors: the pad centre (straight stub), then a point just past each
            # end of the pad along its long axis (a dog-leg stub that leaves a
            # fine-pitch pad straight before turning toward its via)
            bx0, by0, bx1, by1 = pad_g.bounds
            ax_ = (1.0, 0.0) if bx1 - bx0 >= by1 - by0 else (0.0, 1.0)
            reach = max(bx1 - bx0, by1 - by0) / 2 + 0.35
            anchors = [None] + [(q[0] + sgn * reach * ax_[0], q[1] + sgn * reach * ax_[1]) for sgn in (-1, 1)]
            best_path = None
            for anchor in anchors:
                o = anchor or q
                for k in range(0, 60):
                    dist = (r0 if anchor is None else 0.0) + via_r + clear_of(net) + 0.05 * k
                    for j in range(24):
                        a = away + (j // 2 + 1) * (math.pi / 12) * (1 if j % 2 else -1) if j else away
                        v = Point(o[0] + dist * math.cos(a), o[1] + dist * math.sin(a))
                        vd = v.buffer(via_r)
                        if not edge.contains(v) or vd.intersects(pad_g) or smd_u.distance(v) < via_r + B.VIA_PAD_WEB:
                            continue
                        if net != "GND" and pair_u.distance(v) < B.CAN_W / 2 + B.REF_MARGIN + via_r + 0.25 + 0.05:
                            continue   # its In1 antipad would open a void under a pair
                        if any(v.distance(w) < B.JLC["via_drill"] + B.JLC["hole_to_hole"] + 0.05 for w, _ in vias):
                            continue
                        path = [q, (v.x, v.y)] if anchor is None else [q, anchor, (v.x, v.y)]
                        stub = LineString(path).buffer(stub_w / 2)
                        if os.environ.get("LGW_DEBUG") == f"{ref}.{p.GetNumber()}" and anchor and j in (0, 12, 22, 23):
                            print("dbg", anchor, round(v.x, 2), round(v.y, 2), free(vd, net), free(stub, net),
                                  [n for g, n in added if g.distance(stub) < 0.32][:3])
                        if free(vd, net) and free(stub, net):
                            best, best_path = v, path
                            break
                    if best:
                        break
                if best:
                    break
            if best is None:
                if os.environ.get("LGW_DEBUG"):
                    v = Point(q[0] + (r0 + 0.5) * math.cos(away), q[1] + (r0 + 0.5) * math.sin(away))
                    print("dbg", ref, q, away, r0, [(obst[i][1], round(obst[i][0].distance(v.buffer(via_r)), 3))
                                                    for i in tree.query(v.buffer(via_r + 0.32))][:6])
                failed.append((ref, p))
                continue
            pos = (round(best.x, 3), round(best.y, 3))
            via = K.PCB_VIA(b)
            via.SetPosition(pt(*pos))
            via.SetWidth(mm(B.JLC["via_diameter"]))
            via.SetDrill(mm(B.JLC["via_drill"]))
            via.SetNet(nets[net])
            via.SetLocked(True)
            b.Add(via)
            best_path[-1] = pos
            best_path = [(round(x, 4), round(y, 4)) for x, y in best_path]
            for s0, s1 in zip(best_path, best_path[1:]):
                add_track(b, nets, net, stub_w, s0, s1)
            vias.append((Point(pos), net))
            added.append((Point(pos).buffer(via_r), net))
            added.append((LineString(best_path).buffer(stub_w / 2), net))
            placed += 1
      todo = failed
    # last resort: a straight stub to the nearest same-net pad of another part
    # that already has its via (a decoupling cap next to an IC pin, say)
    left = []
    for ref, p in todo:
        q = to_board(p.GetPosition())
        cands = sorted((math.dist(q, to_board(o.GetPosition())), r2, o) for r2, f2 in fps.items() if r2 != ref
                       for o in f2.Pads() if o.GetNetname() == p.GetNetname() and o.GetAttribute() == K.PAD_ATTRIB_SMD)
        for d, r2, o in cands:
            if d > 2.5 or (r2, o) in todo:
                continue
            if os.environ.get("LGW_DEBUG"):
                print("dbg-share", ref, p.GetNumber(), r2, o.GetNumber(), round(d, 2))
            e = to_board(o.GetPosition())
            stub = LineString([q, e]).buffer(stub_w / 2)
            if free(stub, p.GetNetname()):
                add_track(b, nets, p.GetNetname(), stub_w, q, e)
                added.append((stub, p.GetNetname()))
                break
        else:
            left.append((ref, p))
    todo = left
    for ref, p in todo:
        print(f"fanout: no spot for {ref}.{p.GetNumber()} ({p.GetNetname()})")
    return placed


def silk_cleanup(b):
    """Drop library silkscreen strokes that would print on a pad opening, run
    off the board or touch another part's silkscreen (JLC clips or smears
    these anyway; the DRC flags them). Our own silkscreen (logo, text, pin-1
    marks) is placed clear and is not touched."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    gap = B.JLC["silk_to_pad"] + 0.01
    mask = unary_union([poly_of(p, K.F_Mask, gap) for fp in b.GetFootprints() for p in fp.Pads()
                        if p.IsOnLayer(K.F_Mask)])
    inside = box(0, 0, B.W, B.H).buffer(-0.2)
    kept = []   # (geom, ref)
    removed = 0
    for fp in sorted(b.GetFootprints(), key=lambda f: natural(f.GetReference())):
        if fp.GetReference() in B.BOARD_ONLY:
            continue
        for g in list(fp.GraphicalItems()):
            if g.GetLayer() != K.F_SilkS or g.GetClass() != "PCB_SHAPE":
                continue
            sg = poly_of(g, K.F_SilkS)
            bad = (sg.intersects(mask) or not inside.contains(sg)
                   or any(o != fp.GetReference() and sg.distance(k) < gap for k, o in kept))
            if bad:
                fp.Remove(g)
                removed += 1
            else:
                kept.append((sg, fp.GetReference()))
    return removed


def build_placed():
    """Phase 1: project, board, parts, critical routes, silkscreen, planes."""
    out = os.path.dirname(B.PCB)
    write_project(os.path.join(out, "leaf_gw.kicad_pro"))
    write_rules(os.path.join(out, "leaf_gw.kicad_dru"))
    nl = Netlist.load(B.NETLIST)
    b = K.BOARD()
    b.SetCopperLayerCount(4)
    ds = b.GetDesignSettings()
    ds.m_TentViasFront = True    # vias tented both sides: no mask openings, silkscreen may cross them
    ds.m_TentViasBack = True
    outline(b)
    fps, nets = populate(b, nl)
    board_only(b)
    print("stage: placed")
    critical(b, fps, nets)
    print("stage: critical routes")
    fanout(b, fps, nets)
    print("stage: fanout")
    import repair

    def rv(net, pos):
        v = K.PCB_VIA(b)
        v.SetPosition(pt(*pos))
        v.SetWidth(mm(B.JLC["via_diameter"]))
        v.SetDrill(mm(B.JLC["via_drill"]))
        v.SetNet(nets[net])
        v.SetLocked(True)
        b.Add(v)
        return v
    jobs = [] if os.environ.get("LGW_NO_PREROUTE") else routes.PREROUTE   # dev: placement checks only
    done, failed = repair.preroute(b, jobs, lambda n, w, a, c, lay: add_track(b, nets, n, w, a, c, lay), rv)
    print(f"preroute: {done}; failed {failed}")
    silk_cleanup(b)
    silkscreen(b)
    planes(b, nets)
    K.SaveBoard(B.PCB, b)
    return fps


ROUTE_ROUNDS = 1


def build_routed(route=True):
    """Phase 2, in a fresh process so pcbnew reads leaf_gw.kicad_pro (net classes)."""
    b = K.LoadBoard(B.PCB)
    nets = {ni.GetNetname(): ni for ni in b.GetNetsByName().values()}
    if route:
        work = os.environ.get("LGW_WORK") or os.path.join(B.HERE, ".work")
        os.makedirs(work, exist_ok=True)
        # freerouting stops when a pass no longer improves; handing its result
        # back to it (now as ordinary, rippable wiring) lets it finish the last
        # few connections. The round count is fixed, so the result is too.
        print("stage: freerouting")
        for rnd in range(ROUTE_ROUNDS):
            autoroute(b, work, int(os.environ.get("LGW_PASSES", "150")))
            fps = {fp.GetReference(): fp for fp in b.GetFootprints()}
            if len([t for t in b.GetTracks() if t.GetNetname() == "CAN0_H"]) == 0:
                critical(b, fps, nets)   # SES import replaced the wiring: put the pairs back
            fill(b)
            b.BuildConnectivity()
            left = b.GetConnectivity().GetUnconnectedCount(True)
            print(f"routing round {rnd + 1}: {left} unrouted")
            if left == 0:
                break
        import repair

        def rv(net, pos):
            v = K.PCB_VIA(b)
            v.SetPosition(pt(*pos))
            v.SetWidth(mm(B.JLC["via_diameter"]))
            v.SetDrill(mm(B.JLC["via_drill"]))
            v.SetNet(nets[net])
            b.Add(v)
            return v
        # repair what is open; a track freerouting necked below the minimum that
        # can't be widened in place is taken out and its gap repaired at full width
        for attempt in range(2):
            for _ in range(3 if left else 0):   # a net may be in three pieces; one join per net per pass
                done, failed = repair.repair(b, lambda n, w, a, c, lay: add_track(b, nets, n, w, a, c, lay), rv)
                print(f"repair: routed {done}, still open {failed}")
                if not done:
                    break
            stuck = widen_necks(b)
            if not stuck or attempt:
                break
            for t in stuck:
                print(f"  necked {t.GetNetname()} {K.ToMM(t.GetWidth()):.3f} mm at {to_board(t.GetStart())}: re-route")
                b.Delete(t)
            fill(b)
            b.BuildConnectivity()
            left = b.GetConnectivity().GetUnconnectedCount(True)
    if route:
        work = os.environ.get("LGW_WORK") or os.path.join(B.HERE, ".work")
        K.SaveBoard(os.path.join(work, "routed.kicad_pcb"), b)   # dev: the post-route passes start here
        print(f"power vias twinned: {twin_power_vias(b, nets)}")
    print("stage: zones")
    pours(b, nets)
    fill(b)
    if route:
        n = drop_dangling(b)
        print(f"dangling vias/tracks removed: {n}")
        fill(b)
        e, i, c = stitch_gnd(b, nets)   # last: removing a track reshapes the pour islands
        print(f"GND stitching: {e} edge vias, {i} island vias, {c} islands cut out")
        fill(b)
    K.SaveBoard(B.PCB, b)
    normalise(B.PCB)
    write_project(os.path.join(os.path.dirname(B.PCB), "leaf_gw.kicad_pro"))   # SaveBoard rewrote it


ROUTE_ATTEMPTS = 6


def validate(path):
    """What would fail check_layout.sh on this board: DRC (errors, warnings,
    unconnected items) and the layout checks. [] when valid."""
    import tempfile
    assert os.path.exists(os.path.join(os.path.dirname(path), "leaf_gw.kicad_dru")), "DRC needs the rules beside the board"
    with tempfile.TemporaryDirectory() as tmp:
        rpt = os.path.join(tmp, "drc.json")
        subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json", "-o", rpt, path],
                       capture_output=True)
        r = json.load(open(rpt))
    bad = []
    v, u = r.get("violations", []), r.get("unconnected_items", [])
    if v or u:
        bad.append(f"DRC {len(v)} violations, {len(u)} unconnected")
    chk = subprocess.run([sys.executable, os.path.join(B.BOARD_DIR, "checks", "layout.py"), path],
                         capture_output=True, text=True, cwd=os.path.join(B.BOARD_DIR, "checks"))
    if chk.returncode:
        lines = chk.stdout.splitlines()
        bad += [ln.split()[1] for ln in lines if ln.startswith("FAIL")] or ["layout checks"]
        for i, ln in enumerate(lines):   # the first finding of each failed check, for the log
            if ln.startswith("FAIL") and i + 1 < len(lines):
                print("   ", ln.split()[1], lines[i + 1].strip())
    return bad


def drop_dangling(b):
    """Delete vias and tracks the DRC would call dangling (KiCad's own test: a
    via joined on fewer than two layers, a track with a loose end), repeatedly,
    since removing one can leave the next loose. freerouting, the repair and
    the fixed escapes leave a few behind."""
    removed = 0
    while True:
        b.BuildConnectivity()
        conn = b.GetConnectivity()
        drop = [t for t in b.GetTracks()
                if (via_layers(b, t) < 2 if t.GetClass() == "PCB_VIA" else conn.TestTrackEndpointDangling(t, True))]
        base = conn.GetUnconnectedCount(True)
        gone = 0
        for t in drop:
            # only if nothing comes apart without it (the test is per item; a
            # loose stub may still be the one joining a pad to a zone)
            pos, code = t.GetPosition(), t.GetNetCode()
            t.SetNetCode(0)   # out of its net for the count (moved off the board it would count as an island)
            b.BuildConnectivity()
            t.SetNetCode(code)
            if b.GetConnectivity().GetUnconnectedCount(True) > base:
                continue
            print(f"  dangling {t.GetClass()[4:].lower()} {t.GetNetname()} at {to_board(pos)}")
            b.Delete(t)
            gone += 1
        if not gone:
            return removed
        removed += gone


def via_layers(b, v):
    """How many copper layers a via is joined on (a track, pad or filled zone
    of its net touching it there); the DRC calls a via on fewer than two dangling."""
    net, c, r = v.GetNetCode(), v.GetPosition(), mm(B.JLC["via_diameter"] / 2)
    lays = {t.GetLayer() for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetCode() == net and t.HitTest(c, r)}
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() == net and p.HitTest(c, r):
                lays |= {lay for lay in (K.F_Cu, K.In1_Cu, K.In2_Cu, K.B_Cu) if p.IsOnLayer(lay)}
    for z in b.Zones():
        if z.GetNetCode() == net:
            lays |= {lay for lay in (K.F_Cu, K.In1_Cu, K.In2_Cu, K.B_Cu)
                     if z.IsOnLayer(lay) and z.HitTestFilledArea(lay, c, r + mm(0.3))}
    return len(lays)


def widen_necks(b):
    """freerouting necks tracks down between close pads, sometimes below the
    JLC minimum. Bring every routed track up to its floor (0.127 mm, 0.5 mm for
    12 V). Returns the tracks where that would crowd another net."""
    from shapely.strtree import STRtree
    floor = {n: B.V12_W for n in B.NET_CLASSES["12V"][2]}
    clear = max(c for _, c, _ in B.NET_CLASSES.values()) + 0.001   # the DRC's net-class clearance
    other = []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            for lay in (K.F_Cu, K.B_Cu):
                if p.IsOnLayer(lay):
                    other.append((lay, p.GetNetname(), poly_of(p, lay)))
    tracks = list(b.GetTracks())   # one set of wrappers, so `o[3] is t` finds a track's own entry
    for t in tracks:
        for lay in (K.F_Cu, K.B_Cu):
            if t.IsOnLayer(lay):
                other.append((lay, t.GetNetname(), poly_of(t, lay), t))
    stuck = []
    for t in tracks:
        if t.GetClass() != "PCB_TRACK" or t.IsLocked():
            continue
        want = floor.get(t.GetNetname(), B.JLC["track_min"])
        if K.ToMM(t.GetWidth()) >= want - 1e-6:
            continue
        old = t.GetWidth()
        t.SetWidth(mm(want))
        g = poly_of(t, t.GetLayer())
        ok = all(o[1] == t.GetNetname() or o[0] != t.GetLayer() or (len(o) > 3 and o[3] is t)
                 or o[2].distance(g) >= clear for o in other)
        if not ok:
            t.SetWidth(old)
            stuck.append(t)
    return stuck


UUID_RE = re.compile(r'(\((?:uuid|tstamp) )"?([0-9a-fA-F-]{36})"?')


def normalise(path):
    """pcbnew gives every item a random UUID: renumber them in file order from a
    fixed namespace, so the same inputs give the same file."""
    with open(path) as fh:
        text = fh.read()
    seen = {}
    ns = uuid.UUID("5e1f6a3c-0d4b-4c8e-9a51-1eaf9a7e0001")

    def sub(m):
        u = m.group(2).lower()
        if u not in seen:
            seen[u] = str(uuid.uuid5(ns, str(len(seen))))
        return f'{m.group(1)}"{seen[u]}"'
    text = UUID_RE.sub(sub, text)
    with open(path, "w") as fh:
        fh.write(text)


def redo_silkscreen():
    """Replace the logo and the board silkscreen text on the saved board with
    what silkscreen() draws now, touching nothing else (no copper, no fills):
    for silkscreen-only changes without a re-route."""
    b = K.LoadBoard(B.PCB)
    for fp in list(b.GetFootprints()):
        if fp.GetReference() == "LOGO":
            b.Delete(fp)
    for d in list(b.GetDrawings()):
        if d.GetLayer() in (K.F_SilkS, K.B_SilkS) and (d.GetClass() == "PCB_TEXT" or
                                                        (d.GetClass() == "PCB_SHAPE" and d.GetShape() == K.SHAPE_T_POLY)):
            b.Delete(d)
    silkscreen(b)
    K.SaveBoard(B.PCB, b)
    normalise(B.PCB)
    write_project(os.path.join(os.path.dirname(B.PCB), "leaf_gw.kicad_pro"))   # SaveBoard rewrote it


if __name__ == "__main__":
    if "--silk-only" in sys.argv:
        redo_silkscreen()
    elif "--phase2" in sys.argv:
        build_routed(route="--no-route" not in sys.argv)
    else:
        build_placed()
        args = [sys.executable, os.path.abspath(__file__), "--phase2"] + [a for a in sys.argv[1:] if a == "--no-route"]
        if "--no-route" in sys.argv:
            subprocess.run(args, check=True)
            sys.exit(0)
        # freerouting is not deterministic (same input, a few different tracks
        # each run), so a run can leave a connection open. Route again from the
        # placed board until the result is valid; the number of tries is fixed.
        import shutil
        placed = B.PCB + ".placed"
        shutil.copy(B.PCB, placed)
        for attempt in range(1, ROUTE_ATTEMPTS + 1):
            shutil.copy(placed, B.PCB)
            subprocess.run(args, check=True)
            bad = validate(B.PCB)
            print(f"route attempt {attempt}: {'valid' if not bad else '; '.join(bad)}")
            if not bad:
                os.remove(placed)
                break
        else:
            raise SystemExit(f"no valid board after {ROUTE_ATTEMPTS} routing attempts")
