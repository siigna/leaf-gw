"""Checks on the case geometry, independent of how case.py builds it: each
works on the built solids and holds them to requirements stated here (or the
screw's datasheet numbers in case.py), not to case.py's own parameters.

    kicad-python checks.py            # every check; exit 1 if any fails

Each check returns a list of findings (empty = pass). test_mutations.py
breaks the case in memory and asserts the intended check fails.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from manifold3d import Manifold, Mesh

import board3d as B3
import case as C

MIN_CLEAR = 0.3       # case to any part body, board edge or header: print error plus board tolerance
MIN_WALL = 1.0        # thinnest printed section: two 0.45 mm perimeters, overlapped
SEAT_RING = 0.8       # bearing ring around each mounting hole, both faces of the board
SCREW_MINOR = 1.5     # M2 self-tapping screw core: the pilot hole must clear it
MIN_ENGAGE = 3.0      # thread engaged in the tray: 1.5 x d for a screw into plastic
MIN_SKIN = 0.8        # floor left under the blind pilot hole: back stays closed and flat
USB_MIN_CLEAR = 0.2   # around the USB-C spec's max overmold (case.USB_PLUG)
LED_VIEW_D = 1.6      # clear light path straight above each LED
PIN_PATH_D = 1.0      # paperclip path straight above the DFU button
WINDOW_MAX = 1.0      # "snug": lid material within this of each header body, all round
BED = 180.0           # SPEC: fits a 180 mm bed
OVERHANG = 45.0       # degrees from vertical a downward face may lean, unsupported
BRIDGE_MAX = 5.0      # a flat downward face this narrow (both ends supported) bridges
BASE_FRACTION = 0.5   # bed contact >= this x the part's footprint just above the bed
FINGER = 10.0         # room beside a seated plug: both ends (push in) and the lock side
WIRE_UP = 35.0        # Molex: no bundling within 35 mm of the plug, wires leave upward
PLUG_STEP = os.environ.get("LGW_PLUG_STEP", "/tmp/lgw/plug/5016461800.stp")


def mesh(m):
    import trimesh
    g = m.to_mesh()
    return trimesh.Trimesh(g.vert_properties[:, :3], g.tri_verts, process=False)


def vol(a, b):
    return (a ^ b).volume()


def ring(x, y, r0, r1, z0, z1):
    return C.cyl(x, y, 2 * r1, z0, z1) - C.cyl(x, y, 2 * r0, z0 - 1, z1 + 1)


def full(part, probe, what):
    """probe must be (almost) all material."""
    v, f = probe.volume(), vol(part, probe)
    return [] if f >= 0.98 * v else [f"{what}: {100 * f / v:.0f}% material, want >= 98%"]


def empty(part, probe, what):
    f = vol(part, probe)
    return [] if f < 1e-4 else [f"{what}: {f:.3f} mm3 of case in it"]


def valid(parts):
    """Both parts are non-empty closed solids (a bad parameter can make
    manifold return an empty result, which every other check would pass)."""
    return [f"{n}: {m.status().name}, {m.volume():.0f} mm3" for n, m in parts.items()
            if m.status().name != "NoError" or m.volume() < 1000]


def clearance(parts):
    """No case part within MIN_CLEAR of a part body (hulls of KiCad's models,
    header boxes, pin tails), and the board itself only touched on the seat
    faces: nothing inside its outline, nothing within MIN_CLEAR of its edge."""
    out, near = [], []
    solids = B3.solids()
    board = C.slab(C.outline(0), 0, C.T)
    for name, part in parts.items():
        for ref, s in solids:
            g = part.min_gap(s, 5.0)
            near.append((g, f"{name} to {ref}"))
            if g < MIN_CLEAR:
                out.append(f"{name} {'hits' if g == 0 else f'{g:.2f} mm from'} {ref}")
        v = vol(part, board)
        if v > 1e-4:
            out.append(f"{name} is inside the board outline ({v:.2f} mm3)")
        edge = part.slice(C.T / 2) ^ C.outline(MIN_CLEAR)   # mid-board: walls and lip only
        if edge.area() > 1e-4:
            out.append(f"{name} within {MIN_CLEAR} mm of the board edge ({edge.area():.2f} mm2 at mid-board)")
    print("     closest: " + ", ".join(f"{w} {g:.2f} mm" for g, w in sorted(near)[:4]))
    return out


def seated(parts):
    """Board held at both mounting holes: a bearing ring on the tray standoff
    under the board and on the lid boss above it, the screw path open and
    concentric with the hole, the thread long enough, the back closed."""
    out, tray, lid = [], parts["tray"], parts["lid"]
    z_head = C.T + C.HEAD_SEAT
    tip = z_head - C.SCREW_L
    for ref in ("H1", "H2"):
        x, y, drill = B3.hole(ref)
        r = drill / 2
        if drill <= C.SCREW_D:
            out.append(f"{ref}: drill {drill} does not clear an M{C.SCREW_D:g} screw")
        out += full(tray, ring(x, y, r + 0.15, r + 0.15 + SEAT_RING, -0.05, 0), f"{ref} standoff under the board")
        out += full(lid, ring(x, y, r + 0.15, r + 0.15 + SEAT_RING, C.T, C.T + 0.05), f"{ref} lid boss on the board")
        out += empty(tray, C.cyl(x, y, SCREW_MINOR, tip, 0.01), f"{ref} screw path in the tray")
        out += full(tray, ring(x, y, C.SCREW_D / 2 - 0.1, C.SCREW_D / 2 + 0.6, tip, -0.05), f"{ref} thread in the tray")
        out += empty(lid, C.cyl(x, y, C.SCREW_D + 0.1, C.T + 0.01, z_head), f"{ref} screw path in the lid")
        out += empty(lid, C.cyl(x, y, C.HEAD_D + 0.2, z_head + 0.01, C.Z_TOP + 1), f"{ref} head and driver path")
        out += full(lid, ring(x, y, C.SCREW_D / 2 + 0.25, C.HEAD_D / 2 - 0.1, z_head - 0.05, z_head), f"{ref} head seat")
        if -tip < MIN_ENGAGE:
            out.append(f"{ref}: {-tip:.1f} mm of thread in the tray, want >= {MIN_ENGAGE}")
        out += full(tray, C.cyl(x, y, C.SCREW_D, C.Z_FLOOR, C.Z_FLOOR + MIN_SKIN), f"{ref} floor under the pilot")
    return out


def walls(parts, n=20000):
    """Thinnest section >= MIN_WALL: from points spread over each surface, a
    ray inward along the normal to where it leaves the material."""
    import trimesh
    out = []
    for name, part in parts.items():
        m = mesh(part)
        pts, fi = trimesh.sample.sample_surface_even(m, n, seed=1)
        nrm = m.face_normals[fi]
        with np.errstate(divide="ignore", invalid="ignore"):   # trimesh's barycentrics on degenerate hits
            hits, ray, _ = m.ray.intersects_location(pts - nrm * 1e-4, -nrm, multiple_hits=False)
        d = np.linalg.norm(hits - pts[ray], axis=1)
        worst = d.min() if len(d) else 0
        print(f"     {name}: thinnest {worst:.2f} mm over {len(d)} rays")
        if worst < MIN_WALL:
            p = pts[ray][d.argmin()]
            out.append(f"{name}: {worst:.2f} mm thick at ({p[0]:.1f}, {-p[1]:.1f}) board x/y, Z {p[2]:.1f}")
    return out


def openings(parts):
    """USB-C overmold, light paths, paperclip path, header windows, lid height."""
    out, lid = [], parts["lid"]
    x, z, front = C.usb()
    w, h = C.USB_PLUG
    overmold = Manifold.cube([w, C.H + 20 - front, h]).translate([x - w / 2, -(C.H + 20), z - h / 2])
    for name, part in parts.items():
        g = part.min_gap(overmold, USB_MIN_CLEAR + 0.01)
        if g < USB_MIN_CLEAR:
            out.append(f"USB-C overmold {g:.2f} mm from the {name}")
    hulls = dict(B3.solids())
    for ref in C.LEDS:
        lx, ly, _ = C.PL.P[ref]
        top = hulls[ref].bounding_box()[5]
        out += empty(lid, C.cyl(lx, ly, LED_VIEW_D, top, C.Z_TOP + 1), f"{ref} light path")
    sx, sy, _ = C.PL.P["SW1"]
    out += empty(lid, C.cyl(sx, sy, PIN_PATH_D, C.T + B3.SW1_H, C.Z_TOP + 1), "DFU paperclip path")
    for r, (x0, y0, x1, y1) in B3.headers().items():
        snug = B3.box(x0 - WINDOW_MAX - 0.5, y0 - WINDOW_MAX - 0.5, x1 + WINDOW_MAX + 0.5, y1 + WINDOW_MAX + 0.5, C.Z_TOP - 0.5, C.Z_TOP - 0.05) \
            - B3.box(x0 - WINDOW_MAX, y0 - WINDOW_MAX, x1 + WINDOW_MAX, y1 + WINDOW_MAX, -10, 30)
        out += full(lid, snug, f"{r} window snug (lid within {WINDOW_MAX} mm of the body)")
    top = max(p.bounding_box()[5] for p in parts.values())
    if top > B3.header_top() + 1e-6:
        out.append(f"case top Z {top:.2f} is above the header tops ({B3.header_top():.2f})")
    return out


def printed(parts):
    """Each part in its print orientation: fits the bed, sits on a flat face,
    and prints without support. A downward face may lean at most OVERHANG
    from vertical; a flat one is a bridge: each new region a layer adds over
    air must touch the layer below and be at most BRIDGE_MAX across (its
    convex hull's narrow side, i.e. the hole it spans)."""
    import shapely.geometry as sg
    import trimesh
    from manifold3d import JoinType
    out = []
    lim = -np.cos(np.radians(90 - OVERHANG))   # normal Z below this = overhang
    for name, part in parts.items():
        m = C.printed(name, part)
        x0, y0, z0, x1, y1, z1 = m.bounding_box()
        if max(x1 - x0, y1 - y0) > BED or z1 - z0 > BED:
            out.append(f"{name}: {x1 - x0:.1f} x {y1 - y0:.1f} x {z1 - z0:.1f} mm does not fit a {BED:g} mm bed")
        t = mesh(m)
        n, zc = t.face_normals, t.triangles_center[:, 2]
        bed = (n[:, 2] < -0.9999) & (zc < z0 + 1e-3)
        foot = m.slice(z0 + 0.1).area()
        if t.area_faces[bed].sum() < BASE_FRACTION * foot:
            out.append(f"{name}: {t.area_faces[bed].sum():.0f} mm2 on the bed of a {foot:.0f} mm2 footprint")
        flat = (n[:, 2] < -0.9999) & ~bed
        steep = np.where((n[:, 2] < lim) & ~flat & ~bed)[0]
        for g in trimesh.graph.connected_components(t.face_adjacency, nodes=steep, min_len=1):
            g = np.asarray(g)
            c = t.triangles_center[g].mean(0)
            out.append(f"{name}: overhang steeper than {OVERHANG:g} deg, {t.area_faces[g].sum():.1f} mm2 at print ({c[0]:.1f}, {c[1]:.1f}, Z {c[2]:.1f})")
        for z in sorted(set(np.round(zc[flat], 3))):
            above, below = m.slice(z + 0.02), m.slice(z - 0.02)
            grip = below.offset(0.05, JoinType.Square)
            for piece in (above - below).decompose():
                if piece.area() < 0.01:   # tessellation slivers
                    continue
                cx, cy = (np.array(piece.bounds()[:2]) + piece.bounds()[2:]) / 2
                if (piece ^ grip).area() < 1e-4:
                    out.append(f"{name}: {piece.area():.1f} mm2 floats over air at print ({cx:.1f}, {cy:.1f}, Z {z:.2f})")
                    continue
                xy = np.asarray(sg.Polygon(piece.hull().to_polygons()[0]).minimum_rotated_rectangle.exterior.coords)
                span = min(np.linalg.norm(xy[1] - xy[0]), np.linalg.norm(xy[2] - xy[1]))
                print(f"     {name}: bridge {span:.1f} mm at print Z {z:.2f}")
                if span > BRIDGE_MAX:
                    out.append(f"{name}: flat overhang {span:.1f} mm across (bridge max {BRIDGE_MAX:g}) at print ({cx:.1f}, {cy:.1f}, Z {z:.2f})")
    return out


def plug_mesh(step=PLUG_STEP):
    """Molex 501646-1800 STEP as a mesh (gmsh), in its own frame: X along the
    plug, Y down from the top face, Z across (lock bar on +Z)."""
    import trimesh
    stl = os.path.join(tempfile.mkdtemp(), "plug.stl")
    subprocess.run(["gmsh", step, "-2", "-format", "stl", "-clmax", "0.3", "-o", stl], check=True, capture_output=True)
    return trimesh.load(stl)


def seat_plug(t, header):
    """Place the plug mesh seated in a header body (x0, y0, x1, y1), as a
    Manifold in the case frame. Seated depth: the plug's body below its top
    shoulder is narrower than the header (18.6 x 6.0); the lowest section
    still as long as the header body is the shoulder that lands on the header
    top. Returns (manifold, shoulder depth below the plug top, report)."""
    x0, y0, x1, y1 = header
    length, width = y1 - y0, x1 - x0
    v = t.vertices
    ys = np.arange(v[:, 1].min() + 0.02, v[:, 1].max(), 0.05)
    long = [y for y in ys if (s := t.section(plane_origin=[0, y, 0], plane_normal=[0, 1, 0])) is not None
            and np.ptp(s.vertices[:, 0]) >= length - 0.05]
    shoulder = max(long)
    top = 0.0                         # plug top face (the lock bar sits above it, Y < 0)
    lock_z = v[v[:, 1] < top - 0.1][:, 2].mean()
    zmin, zmax = v[:, 2].min(), v[:, 2].max()
    flange = t.section(plane_origin=[0, (top + 0.3), 0], plane_normal=[0, 1, 0]).vertices
    rep = (f"plug STEP: {np.ptp(v[:, 0]):.2f} long x {np.ptp(flange[:, 2]):.2f} wide x {np.ptp(v[:, 1]):.2f} tall; "
           f"shoulder {shoulder - top:.2f} mm below the top face, so {v[:, 1].max() - shoulder:.2f} mm inside the header; "
           f"lock bar on the {'+' if lock_z > (zmin + zmax) / 2 else '-'}Z side")
    # board x across the plug: Z = 0 edge on the header's odd-row side (x0), lock side toward +x
    zz = (v[:, 2] - zmin) if lock_z > (zmin + zmax) / 2 else (zmax - v[:, 2])
    xc = (v[:, 0].min() + v[:, 0].max()) / 2
    out = np.c_[x0 + zz, -((y0 + y1) / 2 + (v[:, 0] - xc)), B3.header_top() + (shoulder - v[:, 1])]
    faces = t.faces if lock_z > (zmin + zmax) / 2 else t.faces[:, ::-1]   # the map mirrors only in that case
    m = Manifold(Mesh(vert_properties=out.astype(np.float32), tri_verts=faces.astype(np.uint32)))
    return m, rep


def plugs(parts, t=None):
    """Both harness plugs seated: the plug bodies, their lock bars, finger room
    at both ends and on the lock side, and WIRE_UP of free space above, all
    clear of the case. Needs the Molex STEP (not in the repo)."""
    if t is None:
        if not os.path.exists(PLUG_STEP) or not shutil.which("gmsh"):
            return None
        t = plug_mesh()
    out, reports = [], []
    for r, hdr in B3.headers().items():
        plug, rep = seat_plug(t, hdr)
        reports.append(f"{r}: {rep}")
        if plug.status().name != "NoError" or plug.volume() <= 0:
            return [f"{r}: plug mesh is not a valid solid ({plug.status()})"]
        x0, y0, x1, y1 = hdr
        room = B3.box(x0, y0 - FINGER, x1 + FINGER, y1 + FINGER, B3.header_top(), B3.header_top() + WIRE_UP)
        for name, part in parts.items():
            g = part.min_gap(plug, MIN_CLEAR + 0.01)
            if g < MIN_CLEAR:
                out.append(f"{r} plug {g:.2f} mm from the {name}")
            out += empty(part, room, f"{r} finger and wire room above the plug ({name})")
    print("  " + "\n  ".join(reports))
    return out


CHECKS = [("parts are valid solids", valid), ("clearance to the board and parts", clearance), ("board seated at both holes", seated),
          ("minimum wall", walls), ("openings: USB-C, LEDs, DFU, header windows, lid height", openings),
          ("printable: bed, flat base, overhangs", printed), ("harness plugs seated, finger room", plugs)]


def main():
    parts = C.build()
    fail = 0
    for title, fn in CHECKS:
        t0 = time.time()
        r = fn(parts)
        title += f" ({time.time() - t0:.0f} s)"
        if r is None:
            print(f"SKIP {title}: needs the Molex 501646-1800 STEP at {PLUG_STEP} (or LGW_PLUG_STEP) and gmsh (.#enclosure)")
            continue
        print(("FAIL " if r else "ok   ") + title)
        for line in r[:20]:
            print("     " + line)
        fail |= bool(r)
    return fail


if __name__ == "__main__":
    sys.exit(main())
