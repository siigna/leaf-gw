"""PNG renders of the case (matplotlib, flat-shaded, no GPU needed).

    kicad-python render.py [out_dir]   # assembled.png, exploded.png, printed.png
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import board3d as B3  # noqa: E402
import case  # noqa: E402

LIGHT = np.array([-0.35, -0.5, 1.0]) / np.linalg.norm([-0.35, -0.5, 1.0])
COLORS = {"tray": "#5b6b7a", "lid": "#9aaab8", "board": "#2f7d4a", "part": "#3a3e44", "header": "#e0d8c4"}
PX = 1400   # image width; height follows the view


def tris(m, dz=0.0):
    mesh = m.to_mesh()
    v = mesh.vert_properties[:, :3] + [0, 0, dz]
    return v[mesh.tri_verts]


def board_solids():
    """(triangles, colour) for the board slab and every part body."""
    out = [(tris(case.slab(case.outline(0), 0, case.T)), COLORS["board"])]
    for name, m in B3.solids():
        if "tail" not in name:
            out.append((tris(m), COLORS["header"] if name in ("J1", "J2") else COLORS["part"]))
    return out


def view(elev, azim):
    """Rotation taking model coordinates to (right, up, toward viewer)."""
    a, e = np.radians(azim), np.radians(elev)
    right = np.array([-np.sin(a), np.cos(a), 0])
    toward = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    return np.array([right, np.cross(toward, right), toward])


def raster(groups, elev, azim):
    """Orthographic z-buffer render: flat Lambert shading plus dark outlines
    where depth or surface direction jumps (matplotlib's painter sort can't
    order interleaved solids)."""
    R = view(elev, azim)
    t = np.concatenate([g for g, _ in groups]) @ R.T
    col = np.concatenate([np.tile(matplotlib.colors.to_rgb(c), (len(g), 1)) for g, c in groups])
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    shade = 0.35 + 0.65 * np.abs(n @ (R @ LIGHT))
    lo, hi = t.reshape(-1, 3).min(0), t.reshape(-1, 3).max(0)
    s = (PX - 40) / max(hi[0] - lo[0], 1e-9)
    h = int((hi[1] - lo[1]) * s) + 40
    xy = (t[:, :, :2] - lo[:2]) * s + 20
    xy[:, :, 1] = h - xy[:, :, 1]
    zbuf = np.full((h, PX), -np.inf)
    img = np.ones((h, PX, 3))
    nid = np.zeros((h, PX), dtype=np.int64) - 1
    for i in range(len(t)):
        p, z = xy[i], t[i, :, 2]
        x0, y0 = np.floor(p.min(0)).astype(int)
        x1, y1 = np.ceil(p.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, PX - 1), min(y1, h - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        (ax_, ay), (bx, by), (cx, cy) = p
        d = (by - cy) * (ax_ - cx) + (cx - bx) * (ay - cy)
        if abs(d) < 1e-12:
            continue
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / d
        w1 = ((cy - ay) * (gx - cx) + (ax_ - cx) * (gy - cy)) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        win = inside & (zz > sub)
        sub[win] = zz[win]
        img[y0:y1 + 1, x0:x1 + 1][win] = col[i] * shade[i]
        nid[y0:y1 + 1, x0:x1 + 1][win] = i
    # outlines: depth steps and creases between neighbouring pixels
    nn = np.where(nid[..., None] >= 0, n[nid.clip(0)], 0)
    edge = np.zeros((h, PX), bool)
    for ax in (0, 1):
        dz = np.abs(np.diff(np.where(np.isfinite(zbuf), zbuf, -1e3), axis=ax))
        dn = 1 - np.sum(np.diff(nn, axis=ax) ** 2, axis=-1) / 2
        e = (dz > 0.6) | (dn < 0.8)
        if ax == 0:
            edge[1:] |= e
        else:
            edge[:, 1:] |= e
    img[edge] *= 0.35
    return img


def save(groups, path, title, elev=28, azim=-60):
    img = raster(groups, elev, azim)
    fig = plt.figure(figsize=(img.shape[1] / 140, img.shape[0] / 140 + 0.4), dpi=140)
    ax = fig.add_axes([0, 0, 1, img.shape[0] / (img.shape[0] + 56)])
    ax.imshow(img, interpolation="antialiased")
    ax.set_axis_off()
    fig.text(0.5, 0.98, title, ha="center", va="top", fontsize=12)
    fig.savefig(path)
    plt.close(fig)


def main(out):
    os.makedirs(out, exist_ok=True)
    parts = case.build()
    brd = board_solids()
    save([(tris(parts["tray"]), COLORS["tray"])] + brd + [(tris(parts["lid"]), COLORS["lid"])],
         os.path.join(out, "assembled.png"), "leaf-gw case, assembled")
    save([(tris(parts["tray"]), COLORS["tray"])] + [(t + [0, 0, 12], c) for t, c in brd]
         + [(tris(parts["lid"], 34), COLORS["lid"])], os.path.join(out, "exploded.png"), "exploded: tray, board, lid")
    for name, m in parts.items():
        save([(tris(case.printed(name, m)), COLORS[name])], os.path.join(out, f"{name}-printed.png"),
             f"{name}, as printed (bed at Z = 0)", elev=35, azim=-55)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(B3.HERE, "out", "render"))
