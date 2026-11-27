"""leaf-gw enclosure: a bottom tray and a lid, generated from the board's numbers.

    kicad-python case.py [out_dir]   # writes tray.stl and lid.stl, each as printed

Frame: board3d.py's (X = board x, Y = -board y, Z = 0 at the board's bottom
face). build() returns both parts assembled around the board; printed() turns
a part onto its print orientation (tray floor down, lid roof down).

The board drops into the tray onto two standoffs under its mounting holes and
two corner posts. The lid's two bosses press it down from above; two screws
go through the lid bosses and the board's holes and cut their own thread in
the tray standoffs. The lid stands 0.2 mm off the tray wall, so the screws
clamp the board and not the walls, and its inner lip closes that seam. Back
face flat (velcro), screw heads on top, zip-tie ears on the two short ends.
"""

import os
import sys

from manifold3d import CrossSection, JoinType, Manifold

import board3d as B3

B, PL = B3.B, B3.PL
SEG = 64

# --- board, from its own files ------------------------------------------------
W, H, CORNER = B.W, B.H, B.CORNER                    # outline (layout/board.py)
T = B3.thickness()                                   # board thickness (pcbnew)
HEADER_TOP = B3.header_top()                         # header top face, Z

# --- shell ----------------------------------------------------------------------
CLEAR_EDGE = 0.5      # board edge to inner wall: JLC outline tolerance (+-0.2) plus print error
WALL = 2.4            # side wall: 6 lines of a 0.4 mm nozzle; halves into the lip joint below
FLOOR = 2.0           # tray floor: 10 layers at 0.2 mm, flat back for velcro
ROOF = 2.0            # lid roof, same
UNDER = 3.0           # floor top to board bottom: header tails stick out 1.6 mm (B3.HEADER_TAIL)
HEADER_PROUD = 0.5    # header top stands this far above the lid, so a seated plug never meets the lid
SEAM = 0.2            # lid wall to tray wall gap: the screws clamp the board, not the walls
LIP_H = 1.5           # lid lip depth into the tray: covers the seam, keeps the halves aligned
LIP_GAP = 0.15        # lip to tray wall, each side: a sliding fit on an FDM print
OUTER_R = CORNER + CLEAR_EDGE + WALL   # outside corner radius follows the board's

# --- screws: M2 x 10 self-tapping (for plastic), pan head ------------------------
# Self-tapping straight into the tray standoff rather than a heat-set insert:
# an M2 insert wants a 3.2 mm hole in a >= 6 mm boss and a soldering iron; the
# case only opens for the termination jumpers and SWD, a few times in its life,
# which a thread cut in ASA/ABS/PETG takes fine.
SCREW_D = 2.0         # M2 major diameter; the board's hole (pcbnew drill) must clear it
SCREW_L = 10.0        # under-head length
HEAD_D = 4.0          # pan head diameter (ISO 7045 M2: 4.0 max)
PILOT_D = 1.7         # tap hole for M2 self-tapping in ABS/ASA/PETG (screw makers give 1.6-1.8)
CLEAR_D = 2.4         # clearance hole through the lid boss
CBORE_D = HEAD_D + 0.6  # counterbore for the head and a 3 mm screwdriver shaft
HEAD_SEAT = 5.0       # head bearing face above the board top: sets thread engagement in the tray
BOSS_D = 5.0          # boss/standoff on the board: the M2 hole footprint's 5 mm keepout circle
BOSS_TOP_D = CBORE_D + 2 * 1.2   # boss around the counterbore: 1.2 mm wall
POST_D = 4.0          # corner posts under the board's other two corners (no parts on the bottom)
POSTS = [(W - 3.0, 3.0), (3.0, H - 3.0)]   # mirror the mounting holes' 3 mm corner offset

# --- openings ------------------------------------------------------------------
WINDOW_CLEAR = 0.4    # header body to lid window, each side: snug, plus print error
USB_PLUG = (12.35, 6.5)   # USB-C spec: max plug overmold width x height
USB_CLEAR = 0.3       # around the overmold, each side
USB_R = 0.5           # slot corner radius: small enough that the overmold's corners keep USB_CLEAR's margin
LED_D = 2.0           # light hole over each LED
PIN_D = 1.5           # DFU pinhole: a 1 mm paperclip, with play
PIN_TUBE_D = PIN_D + 2 * 1.2   # guide tube from the roof down to the button
PIN_TUBE_GAP = 1.0    # tube end above the button's top (B3.SW1_H)
LEDS = ("D11", "D1")  # PWR, STAT

# --- zip-tie ears (2.5 to 4.8 mm ties) ---------------------------------------------
EAR_T = 3.0           # flush with the back
EAR_L = 9.0           # out from the wall
EAR_W = 14.0          # along the end wall
SLOT = (2.2, 5.5)     # x, y: 4.8 mm x 1.3 mm ties with 0.7 mm play; 2.5 mm ties pass too
SLOT_IN = 2.0         # slot's inner edge out from the wall; leaves a 4.8 mm bar outside it

Z_FLOOR = -(UNDER + FLOOR)                 # back face
Z_TOP = HEADER_TOP - HEADER_PROUD          # lid top face
Z_SPLIT = T                                # tray wall top: level with the board's top face


def outline(off):
    """Board outline grown by off (rounded corners stay concentric), 2D."""
    r = CORNER + off
    return CrossSection.square([W - 2 * CORNER, H - 2 * CORNER]).translate([CORNER, -H + CORNER]).offset(r, JoinType.Round, circular_segments=SEG)


def slab(cs, z0, z1):
    return Manifold.extrude(cs, z1 - z0).translate([0, 0, z0])


def cyl(x, y, d, z0, z1):
    """Cylinder at board (x, y)."""
    return Manifold.cylinder(z1 - z0, d / 2, circular_segments=SEG).translate([x, -y, z0])


def rbox(cx, cy, sx, sy, r, z0, z1):
    """Rounded rectangle centred at board (cx, cy), extruded."""
    cs = CrossSection.square([sx - 2 * r, sy - 2 * r], center=True).offset(r, JoinType.Round, circular_segments=SEG) if r else CrossSection.square([sx, sy], center=True)
    return slab(cs.translate([cx, -cy]), z0, z1)


def holes():
    return [B3.hole(r) for r in ("H1", "H2")]


def usb():
    """USB-C plug axis: board x of the receptacle's centre, Z of its mid-height, board y of its front."""
    x0, _, x1, _ = B3.fab_box("J3")
    import json
    pts = json.load(open(B3.HULLS))["J3"]
    top, front = max(p[2] for p in pts), max(-p[1] for p in pts)
    return (x0 + x1) / 2, (T + top) / 2, front


def tie_ears():
    out = Manifold()
    for side in (-1, 1):
        x_wall = (W + CLEAR_EDGE + WALL) if side > 0 else -(CLEAR_EDGE + WALL)
        cx = x_wall + side * EAR_L / 2
        ear = rbox(cx - side * 1.0, H / 2, EAR_L + 2.0, EAR_W, 2.0, Z_FLOOR, Z_FLOOR + EAR_T)   # 1 mm into the wall
        slot_cx = x_wall + side * (SLOT_IN + SLOT[0] / 2)
        out += ear - rbox(slot_cx, H / 2, SLOT[0], SLOT[1], SLOT[0] / 2 - 0.01, Z_FLOOR - 1, Z_FLOOR + EAR_T + 1)
    return out


def usb_cut(part):
    """Slot through the bottom wall around the plug overmold. Square towards
    the part's open edge (the lid's is below, the tray's above), so the
    rounded corners leave no slivers on the seam."""
    x, z, _ = usb()
    w, h = USB_PLUG[0] + 2 * USB_CLEAR, USB_PLUG[1] + 2 * USB_CLEAR
    cs = CrossSection.square([w - 2 * USB_R, h - 2 * USB_R], center=True).offset(USB_R, JoinType.Round, circular_segments=SEG)
    cs += CrossSection.square([w, h / 2 + 20]).translate([-w / 2, -h / 2 - 20 if part == "lid" else 0])
    # profile in X/Z, extruded along -Y through the bottom wall (board y = H side)
    cut = Manifold.extrude(cs, CLEAR_EDGE + WALL + 2).rotate([90, 0, 0])
    return cut.translate([x, -H + 1, z])


def build():
    """{"tray": Manifold, "lid": Manifold}, assembled around the board."""
    inner, mid, outer = outline(CLEAR_EDGE), outline(CLEAR_EDGE + WALL / 2), outline(CLEAR_EDGE + WALL)
    lip_out = outline(CLEAR_EDGE + WALL / 2 - LIP_GAP)

    # tray: floor, outer half-wall to the split, inner half-wall a lip lower
    tray = slab(outer, Z_FLOOR, Z_FLOOR + FLOOR)
    tray += slab(outer - mid, Z_FLOOR, Z_SPLIT)
    tray += slab(mid - inner, Z_FLOOR, Z_SPLIT - LIP_H)
    for x, y, _ in holes():
        tray += cyl(x, y, BOSS_D, Z_FLOOR, 0)
    for x, y in POSTS:
        tray += cyl(x, y, POST_D, Z_FLOOR, 0)
    tray += tie_ears()
    tip = T + HEAD_SEAT - SCREW_L
    for x, y, _ in holes():
        tray -= cyl(x, y, PILOT_D, tip - 0.5, 1)   # 0.5 mm below the tip for chips

    # lid: roof, wall down to the seam, lip inside the tray wall
    z_lid = Z_SPLIT + SEAM
    lid = slab(outer, Z_TOP - ROOF, Z_TOP)
    lid += slab(outer - inner, z_lid, Z_TOP)
    lid += slab(lip_out - inner, Z_SPLIT - LIP_H + SEAM, z_lid)
    z_head = T + HEAD_SEAT
    for x, y, _ in holes():
        lid += cyl(x, y, BOSS_D, T, z_head) + cyl(x, y, BOSS_TOP_D, z_head, Z_TOP)
    sx, sy, _ = PL.P["SW1"]
    lid += cyl(sx, sy, PIN_TUBE_D, T + B3.SW1_H + PIN_TUBE_GAP, Z_TOP)
    lid = lid ^ slab(outer, -100, 100)             # bosses at H1 run into the wall; keep them inside
    for x, y, _ in holes():
        lid -= cyl(x, y, CLEAR_D, T - 1, z_head) + cyl(x, y, CBORE_D, z_head, Z_TOP + 1)
    for r, (x0, y0, x1, y1) in B3.headers().items():
        c = WINDOW_CLEAR
        lid -= B3.box(x0 - c, y0 - c, x1 + c, y1 + c, T, Z_TOP + 1)
    for r in LEDS:
        x, y, _ = PL.P[r]
        lid -= cyl(x, y, LED_D, Z_TOP - ROOF - 1, Z_TOP + 1)
    lid -= cyl(sx, sy, PIN_D, T, Z_TOP + 1)
    return {"tray": tray - usb_cut("tray"), "lid": lid - usb_cut("lid")}


def printed(name, m):
    """Part turned onto the bed: lowest face at Z = 0, centred on X/Y = 0."""
    if name == "lid":
        m = m.rotate([180, 0, 0])
    (x0, y0, z0, x1, y1, _) = m.bounding_box()
    return m.translate([-(x0 + x1) / 2, -(y0 + y1) / 2, -z0])


def save_stl(m, path):
    import trimesh
    mesh = m.to_mesh()
    trimesh.Trimesh(mesh.vert_properties[:, :3], mesh.tri_verts, process=False).export(path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(B3.HERE, "out")
    os.makedirs(out, exist_ok=True)
    for name, m in build().items():
        save_stl(printed(name, m), os.path.join(out, f"{name}.stl"))
        print(name, [round(v, 2) for v in m.bounding_box()], f"{m.volume():.0f} mm3")
