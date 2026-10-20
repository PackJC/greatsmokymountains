"""Check the water against the ground: edges hanging in the air, and water the
ground pokes up through.

    python tools/check_water.py <elevation.npy> <tb_water.txt> [report.json]

Every stream, river and pond object is a flat sheet of water (14 or 24 m wide,
ponds 52 m square, times its scale) placed at its height over the ground, which
the game reads from <elevation.npy> (row 0 = south, 5 m grid). The ground holds
a sheet if
  - along its edges the ground stands at or above the water, so the edge is
    hidden in the bank (an edge with ground below it is water hanging in the
    air), unless another sheet covers that spot at the same level or higher;
  - along its middle the ground lies below the water, so the water shows.
The ground between grid points is a pair of triangles per 5 m cell. Which way
DayZ cuts the cell isn't in the files, so both ways are checked and the worse
counts.
"""

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wvr import transform  # noqa: E402

EASTING = 200000.0
SIZE = 20480.0
TOL_EDGE = 0.05                  # an edge this far over the ground counts as hanging
STEP_PER_SLOPE = 2.0             # over a steep sheet, steps up to this times its pitch's sine more
TOL_COVER = 0.4                  # an edge this little over another sheet's water is a step, not floating
TOL_MID = 0.02                   # ground this far over the water counts as poking through
# Half-extents of each water sheet in its model (from the ODOL headers).
SHEETS = {"stream_14_24": (7.0, 12.0), "stream_14_12": (7.0, 6.01), "stream_14_6": (7.0, 3.02),
          "river_24_24": (12.0, 12.0), "river_24_12": (12.0, 6.01), "river_24_6": (12.0, 3.02),
          "pond_50x50": (26.0, 26.0), "pond_small_01": (28.6, 28.6)}


def read_water(path):
    rows = []
    for line in open(path):
        p = line.strip().rstrip(";").split(";")
        if len(p) < 8:
            continue
        tpl = p[0].strip('"')
        if tpl in SHEETS:
            x, z, yaw, pitch, roll, scale, rel = (float(v) for v in p[1:8])
            rows.append((tpl, x - EASTING, z, yaw, pitch, roll, scale, rel))
    return rows


def ground(elev, x, z):
    """Heights at points under both ways of cutting the cells into triangles, and bilinear."""
    n = elev.shape[0]
    cell = SIZE / n
    u, v = np.clip(x / cell, 0, n - 1.0001), np.clip(z / cell, 0, n - 1.0001)
    j, i = u.astype(int), v.astype(int)
    fx, fz = u - j, v - i
    h00, h01 = elev[i, j], elev[i, j + 1]          # h01: one cell east
    h10, h11 = elev[i + 1, j], elev[i + 1, j + 1]  # h10: one cell north
    # Cut along the diagonal from (east, south) to (west, north).
    lo = fx + fz <= 1
    a = np.where(lo, h00 + (h01 - h00) * fx + (h10 - h00) * fz,
                 h11 + (h10 - h11) * (1 - fx) + (h01 - h11) * (1 - fz))
    # Cut along the diagonal from (west, south) to (east, north).
    lo = fx >= fz
    b = np.where(lo, h00 + (h01 - h00) * fx + (h11 - h01) * fz,
                 h00 + (h10 - h00) * fz + (h11 - h10) * fx)
    bil = h00 * (1 - fx) * (1 - fz) + h01 * fx * (1 - fz) + h10 * (1 - fx) * fz + h11 * fx * fz
    return a, b, bil


def sheets(rows, elev):
    """Each sheet's transform: rows aside, up, dir (scaled) and position, with its world height."""
    n = elev.shape[0]
    cell = SIZE / n
    out = []
    for tpl, x, z, yaw, pitch, roll, scale, rel in rows:
        # build_world: the height is the ground at the position (bilinear) plus rel.
        u, v = min(max(x / cell, 0), n - 1.0001), min(max(z / cell, 0), n - 1.0001)
        j, i = int(u), int(v)
        fx, fz = u - j, v - i
        g = (elev[i, j] * (1 - fx) * (1 - fz) + elev[i, j + 1] * fx * (1 - fz)
             + elev[i + 1, j] * (1 - fx) * fz + elev[i + 1, j + 1] * fx * fz)
        out.append((tpl, np.array(transform(x, g + rel, z, yaw, pitch, roll, scale)), scale))
    return out


def sample_points(tpl, m, step=1.0):
    """Points on a sheet: (local u as a fraction of the half-width, world x, y, z, is the end)."""
    hw, hl = SHEETS[tpl]
    scale = math.sqrt(m[0] ** 2 + m[1] ** 2 + m[2] ** 2)
    nz = max(2, int(math.ceil(2 * hl * scale / step)) + 1)
    lz = np.linspace(-hl, hl, nz)
    fr = np.array([-1.0, -0.95, -0.6, -0.3, 0.0, 0.3, 0.6, 0.95, 1.0])
    if tpl.startswith("pond"):
        fr = np.linspace(-1, 1, max(3, nz))
    LX, LZ = np.meshgrid(fr * hw, lz)
    LX, LZ = LX.ravel(), LZ.ravel()
    p = m[9:12][None, :] + LX[:, None] * m[0:3][None, :] + LZ[:, None] * m[6:9][None, :]
    u = np.abs(LX) / hw
    end = np.abs(LZ) >= hl - 1e-6
    return u, p, end, np.abs(LZ) / hl


class Index:
    def __init__(self, sh, cell=40.0):
        self.sh, self.cell, self.d = sh, cell, {}
        for k, (_, m, _) in enumerate(sh):
            self.d.setdefault((int(m[9] // cell), int(m[11] // cell)), []).append(k)

    def near(self, x, z):
        ci, cj = int(x // self.cell), int(z // self.cell)
        for a in (ci - 1, ci, ci + 1):
            for b in (cj - 1, cj, cj + 1):
                yield from self.d.get((a, b), ())


def covered(idx, k, x, y, z):
    """Is the spot under another sheet's water (its inner part) at this height or higher?"""
    for o in idx.near(x, z):
        if o == k:
            continue
        tpl, m, scale = idx.sh[o]
        hw, hl = SHEETS[tpl]
        dx, dz = x - m[9], z - m[11]                 # where it lies on the sheet, seen from above
        lx = (dx * m[0] + dz * m[2]) / (m[0] ** 2 + m[2] ** 2)
        lz = (dx * m[6] + dz * m[8]) / (m[6] ** 2 + m[8] ** 2)
        if abs(lx) <= 0.95 * hw and abs(lz) <= hl + 0.35:         # pieces' ends part this much at a 2 degree joint
            # The other sheet's surface height here (it may be pitched).
            sy = m[10] + lx * m[1] + lz * m[7]
            if sy >= y - TOL_COVER - STEP_PER_SLOPE * abs(m[7]) / scale:     # a step down a cascade is a fall
                return True
    return False


def check(elev, rows, worst_n=40):
    sh = sheets(rows, elev)
    idx = Index(sh)
    hang, poke, n_edge, n_mid = [], [], 0, 0
    hang_by = {}
    worst = []
    for k, (tpl, m, scale) in enumerate(sh):
        u, p, end, fz = sample_points(tpl, m)
        a, b, _ = ground(elev, p[:, 0], p[:, 2])
        lowest, highest = np.minimum(a, b), np.maximum(a, b)
        edge = (u >= 0.95) | end
        mid = (u <= 0.3) & ~end & (fz < 0.9)
        n_edge += int(edge.sum())
        n_mid += int(mid.sum())
        d_edge = lowest - p[:, 1]
        bad = edge & (d_edge < -TOL_EDGE)
        worst_here = 0.0
        for q in np.nonzero(bad)[0]:
            if covered(idx, k, p[q, 0], p[q, 1], p[q, 2]):
                continue
            hang.append(-d_edge[q])
            worst_here = max(worst_here, -d_edge[q])
        if worst_here > 0:
            kind = tpl.split("_")[0]
            hang_by[kind] = hang_by.get(kind, 0) + 1
            worst.append((worst_here, tpl, float(m[9]), float(m[11])))
        d_mid = highest - p[:, 1]
        poke += [float(v) for v in d_mid[mid & (d_mid > TOL_MID)]]
    worst.sort(reverse=True)
    hang, poke = np.array(hang), np.array(poke)
    return {"sheets": len(sh), "edge_samples": n_edge, "mid_samples": n_mid,
            "hanging_samples": int(len(hang)), "hanging_sheets": hang_by,
            "hang_m": {q: round(float(np.percentile(hang, q)), 2) for q in (50, 90, 99)} if len(hang) else {},
            "hang_over": {t: int((hang > t).sum()) for t in (0.1, 0.25, 0.5, 1.0, 2.0)},
            "poking_samples": int(len(poke)),
            "poke_over": {t: int((poke > t).sum()) for t in (0.05, 0.25, 0.5, 1.0)},
            "worst": [(round(w, 2), t, round(x), round(z)) for w, t, x, z in worst[:worst_n]]}


def main():
    elev = np.load(sys.argv[1]).astype(np.float64)
    rows = read_water(sys.argv[2])
    r = check(elev, rows)
    print("water sheets: %d" % r["sheets"])
    print("edge points hanging over the ground by more than %.2f m, not covered by other water: %d of %d (%.2f%%)"
          % (TOL_EDGE, r["hanging_samples"], r["edge_samples"], 100.0 * r["hanging_samples"] / max(1, r["edge_samples"])))
    print("  sheets with a hanging edge:", r["hanging_sheets"])
    print("  how far they hang (median / 90%% / 99%%): %s" % r["hang_m"])
    print("  points hanging more than 0.1 / 0.25 / 0.5 / 1 / 2 m:", list(r["hang_over"].values()))
    print("middle points with the ground over the water: %d of %d (%.2f%%); over by 0.05 / 0.25 / 0.5 / 1 m: %s"
          % (r["poking_samples"], r["mid_samples"], 100.0 * r["poking_samples"] / max(1, r["mid_samples"]),
             list(r["poke_over"].values())))
    print("worst hanging sheets (m, model, x, z):")
    for w in r["worst"][:15]:
        print("  ", w)
    if len(sys.argv) > 3:
        json.dump(r, open(sys.argv[3], "w"), indent=1)


if __name__ == "__main__":
    main()
