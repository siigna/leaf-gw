"""ESCargot snail (art/escargot-snail.svg) -> silkscreen polygons.

The SVG is potrace output: one <path> of absolute M and relative c/l/z
commands inside a translate/scale group. Curves are flattened, the subpaths
are combined even-odd (a subpath inside another is a hole), the result is
scaled to WIDTH mm and cleaned: features under SILK_MIN wide and gaps under
SILK_MIN are removed morphologically, so what reaches the board is printable.

KiCad graphic polygons have no holes, so each hole is joined to its outer ring
by a zero-width cut (keyholing); keyholed() returns the rings that go into the
footprint, polygons() the logical shapes the checks measure.

    python3 logo.py      # prints size and the measured minimum line and gap
"""

import os
import re

from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

import board as B

SVG = os.path.join(B.BOARD_DIR, "art", "escargot-snail.svg")
WIDTH = 12.0
SILK_MIN = B.JLC["silk_width_min"]
STEPS = 16       # line segments per cubic
EPS_AREA = 1e-4  # mm^2: what the morphological checks may differ by (float noise)


def _cubic(p0, p1, p2, p3):
    for i in range(1, STEPS + 1):
        t = i / STEPS
        u = 1 - t
        yield (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
               u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def subpaths(d):
    """Flattened subpaths of a potrace path string (M absolute; c, l relative)."""
    toks = re.findall(r"[MmCcLlZz]|-?\d+(?:\.\d+)?", d)
    out, cur, pos, cmd, i = [], [], (0.0, 0.0), None, 0
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "zZ":
                if cur:
                    out.append(cur)
                cur = []
            continue
        n = [float(v) for v in toks[i:i + (6 if cmd in "cC" else 2)]]
        if cmd == "M":
            if cur:
                out.append(cur)
            pos = (n[0], n[1])
            cur = [pos]
            cmd = "l"   # implicit lineto after moveto (potrace writes none, but be safe)
            i += 2
        elif cmd == "l":
            pos = (pos[0] + n[0], pos[1] + n[1])
            cur.append(pos)
            i += 2
        elif cmd == "c":
            p1 = (pos[0] + n[0], pos[1] + n[1])
            p2 = (pos[0] + n[2], pos[1] + n[3])
            p3 = (pos[0] + n[4], pos[1] + n[5])
            cur.extend(_cubic(pos, p1, p2, p3))
            pos = p3
            i += 6
        else:
            raise ValueError(f"unsupported path command {cmd!r}")
    if cur:
        out.append(cur)
    return out


def raw_shape():
    with open(SVG) as fh:
        svg = fh.read()
    d = re.search(r'<path d="([^"]+)"', svg, re.S).group(1)
    m = re.search(r'translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)', svg)
    tx, ty, sx, sy = (float(v) for v in m.groups())
    shape = Polygon()
    for sp in subpaths(d):
        if len(sp) >= 3:
            shape = shape.symmetric_difference(Polygon(sp).buffer(0))   # even-odd
    # SVG user units (pt) -> y-down, origin top-left; then scale to WIDTH mm
    shape = affinity.affine_transform(shape, [sx, 0, 0, sy, tx, ty])
    minx, miny, maxx, maxy = shape.bounds
    k = WIDTH / (maxx - minx)
    shape = affinity.affine_transform(shape, [k, 0, 0, k, -minx * k, -miny * k])
    return shape


def cleaned(shape, r=SILK_MIN / 2):
    """Closing then opening at the silkscreen minimum, with a little margin."""
    r = r * 1.05
    shape = shape.buffer(r, join_style="mitre").buffer(-r, join_style="mitre")   # fill thin gaps
    shape = shape.buffer(-r, join_style="mitre").buffer(r, join_style="mitre")   # drop thin lines
    return shape.simplify(0.005)


def polygons():
    """The logo as shapely polygons (with holes), mm, origin at its top-left."""
    s = cleaned(raw_shape())
    return list(getattr(s, "geoms", [s]))


def min_feature_violations(shape, size=SILK_MIN):
    """(thin-line area, thin-gap area): what an opening / closing at size/2 changes."""
    r = size / 2 * 0.999
    opened = shape.buffer(-r, join_style="mitre").buffer(r, join_style="mitre")
    closed = shape.buffer(r, join_style="mitre").buffer(-r, join_style="mitre")
    return shape.difference(opened).area, closed.difference(shape).area


def keyholed(poly):
    """One hole-free ring per polygon: each interior is cut to the exterior along
    the shortest bridge, so the ring traces exterior -> hole -> back."""
    poly = orient(poly, 1.0)      # exterior CCW, holes CW: the cut ring then encloses only the solid
    ext = list(poly.exterior.coords)[:-1]
    for hole in poly.interiors:
        h = list(hole.coords)[:-1]
        best = min(((i, j) for i in range(len(ext)) for j in range(len(h))),
                   key=lambda ij: (ext[ij[0]][0] - h[ij[1]][0]) ** 2 + (ext[ij[0]][1] - h[ij[1]][1]) ** 2)
        i, j = best
        ext = ext[:i + 1] + h[j:] + h[:j + 1] + ext[i:]
    return ext


if __name__ == "__main__":
    ps = polygons()
    u = unary_union(ps)
    minx, miny, maxx, maxy = u.bounds
    thin, gaps = min_feature_violations(u)
    print(f"logo {maxx - minx:.2f} x {maxy - miny:.2f} mm, {len(ps)} polygons, "
          f"{sum(len(p.interiors) for p in ps)} holes; below {SILK_MIN} mm: lines {thin:.5f} mm^2, gaps {gaps:.5f} mm^2")
    raw_thin, raw_gaps = min_feature_violations(raw_shape())
    print(f"before cleaning: lines {raw_thin:.5f} mm^2, gaps {raw_gaps:.5f} mm^2")
    assert thin < EPS_AREA and gaps < EPS_AREA
    # keyholing self-test: a square with two holes survives the round trip
    sq = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)], [[(1, 1), (1, 2), (2, 2), (2, 1)], [(2.5, 2.5), (3.5, 2.5), (3.5, 3.5)]])
    back = Polygon(keyholed(sq)).buffer(0)
    assert abs(back.area - sq.area) < 1e-9 and back.symmetric_difference(sq).area < 1e-9, back.area
    print("keyhole round trip ok")
