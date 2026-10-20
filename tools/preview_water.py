"""Draw an area of the map from above as the ground holds the water: hill shading, the
water wherever it lies over the ground, and any sheet edge hanging in the air in red.

    python tools/preview_water.py <elevation.npy> <tb_water.txt> <x0> <z0> <size m> <out.png> [m per px]
"""

import sys

import numpy as np
from PIL import Image

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from check_water import read_water  # noqa: E402
from water_fit import (SHEETS, bilinear, edge_points, ground, plan_coords, sheet_box,  # noqa: E402
                       sheet_transforms, under_sheets)


def main():
    elev = np.load(sys.argv[1]).astype(np.float64)
    rows = read_water(sys.argv[2])
    x0, z0, size = (float(v) for v in sys.argv[3:6])
    out = sys.argv[6]
    res = float(sys.argv[7]) if len(sys.argv) > 7 else 1.0
    n = int(size / res)
    xs = x0 + (np.arange(n) + 0.5) * res
    zs = z0 + size - (np.arange(n) + 0.5) * res                  # image row 0 = north
    X, Z = np.meshgrid(xs, zs)
    a, b, _ = ground(elev, X.ravel(), Z.ravel())
    g = ((a + b) / 2).reshape(n, n)
    gy, gx = np.gradient(g, res)
    shade = np.clip(0.55 + 0.45 * ((-gx * -0.7 + gy * 0.7) / np.sqrt(gx * gx + gy * gy + 1) + 0.7), 0.3, 1.2)
    img = np.stack([np.full_like(g, 150), np.full_like(g, 165), np.full_like(g, 110)], -1) * shade[..., None]
    rows = [(t, x, z, yaw, p, r, s, rel + float(bilinear(elev, x, z))) for t, x, z, yaw, p, r, s, rel in rows
            if abs(x - x0 - size / 2) < size and abs(z - z0 - size / 2) < size]
    sh = sheet_transforms(rows)
    surf = np.full(n * n, -np.inf)
    P = np.c_[X.ravel(), np.zeros(n * n), Z.ravel()]
    for tpl, m, scale in sh:
        bx0, bz0, bx1, bz1 = sheet_box(tpl, m)
        sel = np.nonzero((P[:, 0] >= bx0) & (P[:, 0] <= bx1) & (P[:, 2] >= bz0) & (P[:, 2] <= bz1))[0]
        if not len(sel):
            continue
        hw, hl = SHEETS[tpl]
        lx, lz = plan_coords(m, P[sel, 0], P[sel, 2])
        ins = (np.abs(lx) <= hw) & (np.abs(lz) <= hl)
        sy = m[10] + lx * m[1] + lz * m[7]
        surf[sel[ins]] = np.maximum(surf[sel[ins]], sy[ins])
    wet = (surf > np.minimum(a, b)).reshape(n, n)
    depth = (surf - np.minimum(a, b)).reshape(n, n)
    water = np.array([60, 120, 190], float) * (0.75 + 0.25 * shade[..., None])
    img = np.where(wet[..., None], water * np.clip(1.1 - depth[..., None] * 0.15, 0.6, 1.1), img)
    pts, owner = edge_points(sh, step=0.5)
    cov = under_sheets(sh, pts, owner)
    ea, eb, _ = ground(elev, pts[:, 0], pts[:, 2])
    hang = (pts[:, 1] - np.minimum(ea, eb) > 0.05) & ~cov
    for x, z in pts[hang][:, [0, 2]]:
        c, r = int((x - x0) / res), int((z0 + size - z) / res)
        if 0 <= r < n and 0 <= c < n:
            img[max(0, r - 1):r + 2, max(0, c - 1):c + 2] = (230, 30, 30)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(out)
    print("%s: %d sheets, %d of %d edge points hanging" % (out, len(sh), int(hang.sum()), len(pts)))


if __name__ == "__main__":
    main()
