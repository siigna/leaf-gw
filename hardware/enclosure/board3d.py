"""The populated board as solids, for building and checking the case.

Frame (shared with KiCad's 3D export): X = board x, Y = -board y, Z up with the
board's bottom face at Z = 0; mm. Board x/y are KiCad's, origin top-left.

Everything the case is checked against comes from the board's own files:
outline (layout/board.py), positions (layout/placement.py), drills, pads and
fab outlines (pcbnew on leaf_gw.kicad_pcb), and part bodies from KiCad's 3D
models. The models are a 450 MB download, so their convex hulls are exported
once into out/board_parts.json (`kicad-python board3d.py`, in
`nix develop .#hardware`) and committed; check.sh re-exports and compares
when the models are present.

    kicad-python board3d.py [out.json]   # export the part hulls
"""

import json
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT = os.path.join(HERE, "..", "board", "layout")
sys.path.insert(0, LAYOUT)
import board as B  # noqa: E402
import placement as PL  # noqa: E402

import pcbnew  # noqa: E402
from manifold3d import Manifold  # noqa: E402

HULLS = os.path.join(HERE, "out", "board_parts.json")

# Parts KiCad has no 3D model for, as boxes from their datasheets.
HEADER_H = 12.0      # Molex SD-501645-001: iGrid header body height above the board
HEADER_TAIL = 1.6    # same drawing: 3.2 mm pin tails through a 1.6 mm board
SW1_H = 2.0          # XKB TS-1187A-B-A-B is 1.5 mm tall; 0.5 mm margin, no drawing in the repo
TH_TAIL = 2.0        # any other through-hole pin: assume up to 2 mm below the board
# The USB-C receptacle's own model is missing; the board's renders use a
# look-alike (layout/colors.py), and so do the hulls.
STAND_INS = __import__("colors").STAND_INS
F1_H = 2.5           # 1812 PTC (mSMD050-60V); KiCad has no Fuse_1812 model; 1812 PTCs are 0.6-1.8 mm thick
BOXED = {"SW1", "F1"}

_board = None


def pcb():
    global _board
    if _board is None:
        _board = pcbnew.LoadBoard(B.PCB)
    return _board


def mm(v):
    return pcbnew.ToMM(v)


def to_board(p):
    """KiCad sheet point -> board (x, y)."""
    return mm(p.x) - B.ORIGIN[0], mm(p.y) - B.ORIGIN[1]


def thickness():
    return mm(pcb().GetDesignSettings().GetBoardThickness())


def fp(ref):
    f = pcb().FindFootprintByReference(ref)
    assert f, ref
    return f


def hole(ref):
    """Mounting hole: board (x, y) and drill diameter, from the footprint."""
    (pad,) = fp(ref).Pads()
    return (*to_board(pad.GetPosition()), mm(pad.GetDrillSizeX()))


def fab_box(ref):
    """Board-frame bbox (x0, y0, x1, y1) of a footprint's biggest F.Fab shape,
    to the line's centre: the part body as the footprint draws it."""
    shapes = [g for g in fp(ref).GraphicalItems() if g.GetLayer() == pcbnew.F_Fab and g.GetClass() == "PCB_SHAPE"]
    g = max(shapes, key=lambda s: s.GetBoundingBox().GetArea())
    bb, w = g.GetBoundingBox(), mm(g.GetWidth()) / 2
    x0, y0 = to_board(pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()))
    x1, y1 = to_board(pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()))
    return x0 + w, y0 + w, x1 - w, y1 - w


def th_pads():
    """(ref, x, y, size_x, size_y) of every plated through-hole pad."""
    out = []
    for f in pcb().GetFootprints():
        for p in f.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                bb = p.GetBoundingBox()
                out.append((f.GetReference(), *to_board(p.GetPosition()), mm(bb.GetWidth()), mm(bb.GetHeight())))
    return out


def box(x0, y0, x1, y1, z0, z1):
    """Board-frame rectangle (y down) extruded from z0 to z1, as a solid in the 3D frame."""
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, -y1, z0])


def model_file(m):
    path = os.path.expandvars(m.m_Filename)
    for real, look in STAND_INS.items():
        path = path.replace(real, look)
    return path


def export_hulls(out=HULLS):
    """Convex hull of each part's 3D model, via kicad-cli, one part at a time."""
    tmp = tempfile.mkdtemp()
    text = open(B.PCB).read()
    for real, look in STAND_INS.items():
        text = text.replace(real, look)
    board = os.path.join(tmp, "b.kicad_pcb")
    open(board, "w").write(text)
    import trimesh
    from scipy.spatial import ConvexHull
    hulls = {}
    for f in sorted(pcb().GetFootprints(), key=lambda f: f.GetReference()):
        ref = f.GetReference()
        files = [model_file(m) for m in f.Models() if m.m_Show]
        if not files:
            continue
        if not all(os.path.exists(x) for x in files):
            # only parts solids() models as a box may lack their model
            assert ref in BOXED, f"{ref}: 3D model missing ({files}); is KICAD10_3DMODEL_DIR set?"
            continue
        stl = os.path.join(tmp, f"{ref}.stl")
        subprocess.run(["kicad-cli", "pcb", "export", "stl", "--no-board-body", "--force", "--user-origin",
                        f"{B.ORIGIN[0]}x{B.ORIGIN[1]}mm", "--component-filter", ref, "-o", stl, board],
                       check=True, capture_output=True)
        if not os.path.exists(stl) or os.path.getsize(stl) < 200:
            raise SystemExit(f"{ref}: no 3D model exported (is KICAD10_3DMODEL_DIR set?)")
        v = trimesh.load(stl).vertices
        hulls[ref] = np.round(v[ConvexHull(v).vertices], 3).tolist()
    with open(out, "w") as fh:
        fh.write("{\n" + ",\n".join(f'"{r}": {json.dumps(hulls[r])}' for r in sorted(hulls)) + "\n}\n")
    return hulls


def headers():
    """J1/J2 bodies (board-frame bbox), from the footprint's F.Fab rectangle."""
    return {r: fab_box(r) for r in ("J1", "J2")}


def solids():
    """[(name, Manifold)]: every part body the case must clear, board slab excluded."""
    t = thickness()
    out = [(ref, Manifold.hull_points(pts)) for ref, pts in json.load(open(HULLS)).items()]
    for r, (x0, y0, x1, y1) in headers().items():
        out.append((r, box(x0, y0, x1, y1, t, t + HEADER_H)))
        out.append((f"{r} tails", box(x0, y0, x1, y1, -HEADER_TAIL, 0)))
    for ref, x, y, sx, sy in th_pads():
        if ref not in ("J1", "J2"):
            out.append((f"{ref} tail", box(x - sx / 2, y - sy / 2, x + sx / 2, y + sy / 2, -TH_TAIL, 0)))
    out.append(("SW1", box(*fab_box("SW1"), t, t + SW1_H)))
    out.append(("F1", box(*fab_box("F1"), t, t + F1_H)))
    return out


def header_top():
    return thickness() + HEADER_H


if __name__ == "__main__":
    h = export_hulls(sys.argv[1] if len(sys.argv) > 1 else HULLS)
    print(f"{len(h)} part hulls")
