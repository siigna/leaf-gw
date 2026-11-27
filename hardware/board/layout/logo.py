"""The silkscreen logo (art/leaf.svg) -> silkscreen polygons.

The SVG's <path> elements are flattened (M L H V C S Q T A Z, absolute and
relative; an optional translate/scale group transform, as potrace writes it,
is applied), the subpaths are combined even-odd (a subpath inside another is a
hole), the result is scaled to WIDTH mm and cleaned: features under SILK_MIN
wide and gaps under SILK_MIN are removed morphologically, so what reaches the
board is printable.

KiCad graphic polygons have no holes, so each hole is joined to its outer ring
by a zero-width cut (keyholing); keyholed() returns the rings that go into the
footprint, polygons() the logical shapes the checks measure.

The back carries a second mark, esd_paw(): an ESD warning triangle with a
paw cut out of it, drawn here from ellipses (our own art, MIT).

    python3 logo.py      # prints size and the measured minimum line and gap
"""

import math
import os
import re

from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

import board as B

SVG = os.path.join(B.BOARD_DIR, "art", "leaf.svg")   # Phosphor Icons "leaf", fill (MIT, art/LICENSE-phosphor-icons)
WIDTH = 10.5     # mm; the largest that fits the clear spot on the top side (placement.LOGO)
SILK_MIN = B.JLC["silk_width_min"]
STEPS = 16       # line segments per cubic
EPS_AREA = 1e-4  # mm^2: what the morphological checks may differ by (float noise)

def _cubic(p0, p1, p2, p3, steps):
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        yield (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
               u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _arc(p0, rx, ry, phi, large, sweep, p1, steps):
    """SVG elliptical arc, endpoint form (SVG 1.1 F.6.5), flattened."""
    if p0 == p1:
        return []
    if rx == 0 or ry == 0:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = c * dx + s * dy, -s * dx + c * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    k = math.sqrt(max(0.0, num / (rx * rx * y1 * y1 + ry * ry * x1 * x1)))
    if large == sweep:
        k = -k
    cx1, cy1 = k * rx * y1 / ry, -k * ry * x1 / rx
    cx, cy = c * cx1 - s * cy1 + (p0[0] + p1[0]) / 2, s * cx1 + c * cy1 + (p0[1] + p1[1]) / 2
    ang = lambda ux, uy, vx, vy: math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    t1 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(2, int(abs(dt) / (math.pi / 32)) + 1)
    out = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        out.append((c * ex - s * ey + cx, s * ex + c * ey + cy))
    out[-1] = p1
    return out


def subpaths(d, steps=16):
    """Flattened subpaths of an SVG path string: M L H V C S Q T A Z, absolute and relative."""
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
    out, cur, pos, start, cmd, i = [], [], (0.0, 0.0), (0.0, 0.0), None, 0
    prev_c = prev_q = None
    argc = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7}
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "zZ":
                if cur:
                    out.append(cur)
                cur, pos = [], start
                prev_c = prev_q = None
            continue
        lc = cmd.lower()
        n = [float(v) for v in toks[i:i + argc[lc]]]
        i += argc[lc]
        rel = cmd.islower()
        ox, oy = pos if rel else (0.0, 0.0)
        pc, pq = None, None
        if lc == "m":
            if cur:
                out.append(cur)
            pos = start = (ox + n[0], oy + n[1])
            cur = [pos]
            cmd = "l" if rel else "L"
        elif lc == "l":
            pos = (ox + n[0], oy + n[1]); cur.append(pos)
        elif lc == "h":
            pos = (ox + n[0] if rel else n[0], pos[1]); cur.append(pos)
        elif lc == "v":
            pos = (pos[0], oy + n[0] if rel else n[0]); cur.append(pos)
        elif lc in "cs":
            if lc == "c":
                p1 = (ox + n[0], oy + n[1]); p2 = (ox + n[2], oy + n[3]); p3 = (ox + n[4], oy + n[5])
            else:
                p1 = (2 * pos[0] - prev_c[0], 2 * pos[1] - prev_c[1]) if prev_c else pos
                p2 = (ox + n[0], oy + n[1]); p3 = (ox + n[2], oy + n[3])
            cur.extend(_cubic(pos, p1, p2, p3, steps)); pos, pc = p3, p2
        elif lc in "qt":
            if lc == "q":
                q1 = (ox + n[0], oy + n[1]); p3 = (ox + n[2], oy + n[3])
            else:
                q1 = (2 * pos[0] - prev_q[0], 2 * pos[1] - prev_q[1]) if prev_q else pos
                p3 = (ox + n[0], oy + n[1])
            p1 = (pos[0] + 2 / 3 * (q1[0] - pos[0]), pos[1] + 2 / 3 * (q1[1] - pos[1]))
            p2 = (p3[0] + 2 / 3 * (q1[0] - p3[0]), p3[1] + 2 / 3 * (q1[1] - p3[1]))
            cur.extend(_cubic(pos, p1, p2, p3, steps)); pos, pq = p3, q1
        elif lc == "a":
            p3 = (ox + n[5], oy + n[6])
            cur.extend(_arc(pos, n[0], n[1], n[2], int(n[3]), int(n[4]), p3, steps)); pos = p3
        prev_c, prev_q = pc, pq
    if cur:
        out.append(cur)
    return out


def raw_shape(svg_path=SVG):
    with open(svg_path) as fh:
        svg = fh.read()
    shape = Polygon()
    for d in re.findall(r'<path[^>]*\sd="([^"]+)"', svg, re.S):
        for sp in subpaths(d, STEPS):
            if len(sp) >= 3:
                shape = shape.symmetric_difference(Polygon(sp).buffer(0))   # even-odd
    m = re.search(r'translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)', svg)
    if m:   # potrace: user units in a flipped group -> y-down, origin top-left
        tx, ty, sx, sy = (float(v) for v in m.groups())
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


ESD_WIDTH = 9.0   # mm, the paw triangle's base


def esd_paw(width=ESD_WIDTH):
    """Solid triangle, apex up, with a paw (pad and four toes) cut out; mm,
    origin at the top-left of its bounding box, y down, cleaned for silkscreen."""
    from shapely.geometry import Point

    def ell(cx, cy, rx, ry, rot=0.0):
        e = affinity.scale(Point(0, 0).buffer(1.0, quad_segs=16), rx, ry)
        return affinity.translate(affinity.rotate(e, rot), cx, cy)
    h = math.sqrt(3) / 2
    r = 0.06    # corner rounding, in units of the base
    tri = Polygon([(0.5, 0), (1, h), (0, h)]).buffer(-r).buffer(r)
    paw = unary_union([ell(0.5, 0.645, 0.13, 0.10),
                       ell(0.33, 0.52, 0.04, 0.055, -25), ell(0.43, 0.43, 0.04, 0.055, -8),
                       ell(0.57, 0.43, 0.04, 0.055, 8), ell(0.67, 0.52, 0.04, 0.055, 25)])
    shape = affinity.scale(tri.difference(paw), width, width, origin=(0, 0))
    minx, miny = shape.bounds[:2]
    return cleaned(affinity.translate(shape, -minx, -miny))


QR_URL = "HTTPS://GITHUB.COM/SIIGNA/LEAF-GW"   # upper case: QR alphanumeric mode, version 2 (25 x 25); GitHub paths ignore case
QR_MODULE = 0.45   # mm
QR_QUIET = 4       # modules of light margin (the QR standard's quiet zone)
# Silkscreen is the light colour on a dark mask (green, black, blue, purple,
# red): the dark modules are left bare. For a white or yellow mask with black
# silkscreen set this True, so the dark modules are printed instead; zbar did
# not read the other polarity there.
QR_DARK_SILK = False


def qr_matrix(text=QR_URL):
    import segno
    q = segno.make(text, error="m", micro=False)
    return [list(row) for row in q.matrix]


def qr(text=QR_URL, module=QR_MODULE):
    """The QR code as silkscreen (see QR_DARK_SILK): a light square, quiet zone
    included, with the dark modules left bare; mm, origin top-left, y down."""
    from shapely.geometry import box
    m = qr_matrix(text)
    n = len(m) + 2 * QR_QUIET
    dark = unary_union([box((c + QR_QUIET) * module, (r + QR_QUIET) * module,
                            (c + QR_QUIET + 1) * module, (r + QR_QUIET + 1) * module)
                        for r, row in enumerate(m) for c, v in enumerate(row) if v])
    if QR_DARK_SILK:
        return dark.simplify(0)
    return box(0, 0, n * module, n * module).difference(dark).simplify(0)


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
    # the parser on the other art: the potrace snail (relative c/l in a flipped group)
    snail = raw_shape(os.path.join(B.BOARD_DIR, "art", "escargot-snail.svg"))
    assert snail.area > 20 and abs(snail.bounds[2] - snail.bounds[0] - WIDTH) < 1e-6, snail.bounds
    # an arc: a half disc of radius 1 has area pi/2
    half = Polygon(subpaths("M0,0 A1,1 0 0,1 2,0 Z")[0])
    assert abs(half.area - math.pi / 2) < 5e-3, half.area   # 32 chords per half turn
    print("path parser ok (arcs, potrace)")
    paw = esd_paw()
    pt, pg = min_feature_violations(paw)
    assert pt < EPS_AREA and pg < EPS_AREA and len(paw.interiors) == 5, (pt, pg, len(paw.interiors))
    print(f"esd paw {paw.bounds[2]:.2f} x {paw.bounds[3]:.2f} mm, 5 cut-outs, lines and gaps >= {SILK_MIN} mm")
    # QR: every module centre reads back as the matrix says (light = silkscreen)
    from shapely.geometry import Point
    m, code = qr_matrix(), qr()
    bad = sum((not code.contains(Point((c + QR_QUIET + 0.5) * QR_MODULE, (r + QR_QUIET + 0.5) * QR_MODULE))) != bool(v)
              for r, row in enumerate(m) for c, v in enumerate(row))
    assert bad == 0 and len(m) == 25, (bad, len(m))
    QR_DARK_SILK = True   # the other polarity: silkscreen exactly where the matrix is dark
    inv = qr()
    QR_DARK_SILK = False
    bad = sum(inv.contains(Point((c + QR_QUIET + 0.5) * QR_MODULE, (r + QR_QUIET + 0.5) * QR_MODULE)) != bool(v)
              for r, row in enumerate(m) for c, v in enumerate(row))
    assert bad == 0, bad
    side = code.bounds[2]
    print(f"qr {len(m)} x {len(m)} modules, {side:.2f} mm square, reads back as encoded")
