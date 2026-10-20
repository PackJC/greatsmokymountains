"""Shape the ground round the water so it holds it: the last step of the source chain,
and the channel code tools/osm_water.py uses.

    python tools/water_fit.py source

Every creek, river and pond is flat sheets of water (the stream, river and pond
models) over a channel in the ground. The terrain is a 5 m grid of heights, cut
into two triangles per cell, so the ground holds a sheet when the grid points
round it are right:
  - under the channel (within `core` of the creek's line, inside a pond's shore):
    the bed, `bed` metres under the water, so the water shows;
  - the banks, out to the sheet's edge: `bank` over the water, so the waterline
    stays well inside the sheet;
  - every point along every sheet's edge lies on ground at or over its water
    (whichever way the cells are cut), unless another sheet's water covers it, and
    the ground along each stream and river sheet's middle lies under its water.
    Round after round, the grid points of the cells where that fails are moved just
    enough: those under a channel only down, the rest only up.

As the last step (after tools/road_build.py, tools/buildings.py, the rocks and
forest, tools/skybridge.py) it does that again on the map's final heights,
source/buildings/elevation.npy, which it rewrites:
  - roads with the ground carved round them, and building pads, are left alone;
  - the water (from source/water/water_roads_abs.json, which tools/road_build.py
    writes) is rewritten relative to the new ground, keeping its heights;
  - buildings, bridges, fences, the SkyBridge and roads keep their heights too;
  - trees, bushes, dead wood, rocks and trail parts follow the ground, and any
    that would now stand in the water are taken out;
  - tools/check_water.py's check runs, and source/water/fit_summary.txt says
    what changed.
"""

import hashlib
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_water import SHEETS, check, ground  # noqa: E402
from wvr import transform  # noqa: E402

EASTING = 200000.0
SIZE = 20480.0
EDGE_DIAG = 5.0 * math.sqrt(2.0)  # the farthest a point is from its cell's grid points
END_TRIM = 5.0                   # a creek's bed stops this short of its ends
JOINT = 0.35                     # at a joint turning up to 2 degrees, the pieces' ends part by this much
COVER_TOL = 0.4                  # an edge this little over another sheet's water is a step, not floating
STEP_PER_SLOPE = 2.0             # plus this times the sine of that sheet's pitch (a fall on a cascade)
OUTER = 0.05                     # least height over the water just past a sheet's edge
EDGE_CLEAR = 0.03                # a sheet's edge must lie at least this far under the ground
MAX_RAISE = 4.0                  # no grid point is raised more than this
MAX_CUT = 8.0                    # nor cut deeper than this
VISIBLE = 0.1                    # the ground under a sheet's middle lies at least this far under its water
MID_HALF = {"stream": 1.0, "river": 2.5}   # the middle kept under water: this far (m) either side of the line
EDGE_REACH = 3.5                 # sheet edges lie this far beyond the channel
ROUNDS = 30
DROP_HANG = 1.0                  # water still hanging this far after the rounds is left out
CULVERT_HANG = 0.3               # water hanging this far over road or pad ground stops short of it
ROAD_HALF = {"asf1": 6.0, "asf2": 4.5, "asf3": 3.5, "grav": 3.0, "mud": 2.5}
ROAD_SHOULDER = 6.0              # tools/road_build.py levels the ground this far past each edge
# Object lists: what keeps its height when the ground under it changes, what follows
# the ground (and goes if it would stand in water).
KEEP_HEIGHT = ["roads/tb_roads_main.txt", "roads/tb_roads_local.txt", "buildings/tb_buildings.txt",
               "buildings/tb_cabins.txt", "buildings/tb_fuel.txt", "buildings/tb_fences.txt",
               "buildings/tb_bridges.txt", "buildings/tb_skybridge.txt"]
FOLLOW_GROUND = ["forest/tb_trees.txt", "forest/tb_bushes.txt", "forest/tb_deadwood.txt", "rocks/tb_rocks.txt",
                 "roads/tb_trails.txt"]


# ---------------------------------------------------------------------- grid helpers

def bilinear(elev, x, z):
    n = elev.shape[0]
    cell = SIZE / n
    u, v = np.clip(np.asarray(x) / cell, 0, n - 1.0001), np.clip(np.asarray(z) / cell, 0, n - 1.0001)
    j, i = u.astype(int), v.astype(int)
    fx, fz = u - j, v - i
    return (elev[i, j] * (1 - fx) * (1 - fz) + elev[i, j + 1] * fx * (1 - fz)
            + elev[i + 1, j] * (1 - fx) * fz + elev[i + 1, j + 1] * fx * fz)


def nodes_near_points(pts, reach, cell, n):
    """Grid points within `reach` of a run of points: flat index (row * n + col), distance,
    and which point is nearest."""
    r = int(math.ceil(reach / cell)) + 1
    di, dj = np.meshgrid(np.arange(-r, r + 1), np.arange(-r, r + 1))
    di, dj = di.ravel(), dj.ravel()
    ci = np.floor(pts[:, 0] / cell).astype(int)
    cj = np.floor(pts[:, 1] / cell).astype(int)
    keys, dist, near = [], [], []
    for s in range(0, len(pts), 4000):                  # in batches: long rivers have many points
        ii = ci[s:s + 4000, None] + di[None, :]
        jj = cj[s:s + 4000, None] + dj[None, :]
        d = np.hypot(ii * cell - pts[s:s + 4000, 0:1], jj * cell - pts[s:s + 4000, 1:2])
        st = np.broadcast_to(np.arange(s, s + len(ii))[:, None], d.shape)
        ok = (ii >= 0) & (ii < n) & (jj >= 0) & (jj < n) & (d <= reach)
        keys.append((jj * n + ii)[ok])
        dist.append(d[ok])
        near.append(st[ok])
    key, d, st = np.concatenate(keys), np.concatenate(dist), np.concatenate(near)
    order = np.lexsort((d, key))
    key, d, st = key[order], d[order], st[order]
    first = np.r_[True, key[1:] != key[:-1]]
    return key[first], d[first], st[first]


def inside_polygon(x, z, poly):
    poly = np.asarray(poly, float)
    inside = np.zeros(len(x), bool)
    for (x1, z1), (x2, z2) in zip(poly, np.roll(poly, -1, axis=0)):
        cross = (z1 > z) != (z2 > z)
        xs = (x2 - x1) * (z - z1) / np.where(z2 != z1, z2 - z1, 1e-12) + x1
        inside ^= cross & (x < xs)
    return inside


def distance_to_polygon(x, z, poly):
    poly = np.asarray(poly, float)
    best = np.full(len(x), np.inf)
    for (x1, z1), (x2, z2) in zip(poly, np.roll(poly, -1, axis=0)):
        dx, dz = x2 - x1, z2 - z1
        t = np.clip(((x - x1) * dx + (z - z1) * dz) / max(dx * dx + dz * dz, 1e-12), 0, 1)
        best = np.minimum(best, np.hypot(x - (x1 + t * dx), z - (z1 + t * dz)))
    return best


# ---------------------------------------------------------------------- channel targets

def channel_targets(shape, channels):
    """For every grid point: the bed level where it lies under a channel (the lowest
    asked for), the least height the banks need there (the highest asked for), and
    whether it's in a bank (between a channel and its sheets' edges): those are set
    to the bank height and left there, so the waterline stays put."""
    n = shape[0]
    cell = SIZE / n
    bed = np.full(n * n, np.inf)
    bank = np.full(n * n, -np.inf)
    in_banks = np.zeros(n * n, bool)
    for ch in channels:
        kind = ch["kind"]
        if kind == "line":
            pts = np.asarray(ch["points"], float)
            surf = np.asarray(ch["surface"], float)
            half, core = ch["half"], ch["core"]
            key, d, st = nodes_near_points(pts, half + EDGE_DIAG, cell, n)
            S = surf[st]
            nx, nz = (key % n) * cell, (key // n) * cell
            # Past either end, the bed doesn't go on: those points are bank.
            beyond = np.zeros(len(key), bool)
            for end, inner in ((0, 1), (len(pts) - 1, len(pts) - 2)):
                if len(pts) < 2:
                    break
                t = pts[end] - pts[inner]
                t = t / (np.hypot(*t) or 1)
                m = st == end
                beyond[m] = ((nx[m] - pts[end, 0]) * t[0] + (nz[m] - pts[end, 1]) * t[1]) > 0.5
            # Nor right up to either end: the ground rises round where the water starts
            # or stops, so the sheet's end lies on it (a creek's end on another creek is
            # under that creek's water anyway).
            arc = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
            near_end = (arc[st] < END_TRIM) | (arc[st] > arc[-1] - END_TRIM)
            in_core = (d <= core) & ~beyond & ~near_end
            in_bank = ~in_core & (d <= half)
            outer = ~in_core & ~in_bank
            np.minimum.at(bed, key[in_core], S[in_core] - ch["bed"])
            np.maximum.at(bank, key[in_bank], S[in_bank] + ch["bank"])
            in_banks[key[in_bank]] = True
            np.maximum.at(bank, key[outer], S[outer] + OUTER)
        else:                                            # pond or pool
            level = ch["level"]
            if kind == "pond":
                poly = np.asarray(ch["polygon"], float)
                x0, z0 = poly.min(0) - ch["reach"]
                x1, z1 = poly.max(0) + ch["reach"]
            else:
                c = np.asarray(ch["center"], float)
                x0, z0 = c - ch["reach"]
                x1, z1 = c + ch["reach"]
            i0, i1 = max(0, int(x0 / cell)), min(n - 1, int(x1 / cell) + 1)
            j0, j1 = max(0, int(z0 / cell)), min(n - 1, int(z1 / cell) + 1)
            jj, ii = np.mgrid[j0:j1 + 1, i0:i1 + 1]
            jj, ii = jj.ravel(), ii.ravel()
            nx, nz = ii * cell, jj * cell
            if kind == "pond":
                inside = inside_polygon(nx, nz, poly)
                d = np.where(inside, 0.0, distance_to_polygon(nx, nz, poly))
            else:
                d = np.maximum(np.hypot(nx - c[0], nz - c[1]) - ch["radius"], 0.0)
                inside = d <= 0
            key = jj * n + ii
            np.minimum.at(bed, key[inside], level - ch["depth"])
            b = ~inside & (d <= ch["shore"])
            np.maximum.at(bank, key[b], level + ch["bank"])
            in_banks[key[b]] = True
            o = ~inside & (d > ch["shore"]) & (d <= ch["reach"])
            np.maximum.at(bank, key[o], level + OUTER)
    return bed.reshape(shape), bank.reshape(shape), in_banks.reshape(shape)


def apply_targets(elev, bed, bank, protect=None):
    """Set the beds (never cutting more than MAX_CUT into the ground), raise the banks
    (never more than MAX_RAISE); returns the grid points under a channel."""
    core = np.isfinite(bed)
    if protect is not None:
        core &= ~protect
    elev[core] = np.maximum(bed[core], elev[core] - MAX_CUT)
    b = np.isfinite(bank) & ~core
    if protect is not None:
        b &= ~protect
    elev[b] = np.maximum(elev[b], np.minimum(bank[b], elev[b] + MAX_RAISE))
    return core


# ---------------------------------------------------------------------- sheets and their edges

def sheet_transforms(rows):
    """rows: (template, x, z, yaw, pitch, roll, scale, absolute height) -> (template, m12, scale)."""
    return [(tpl, np.array(transform(x, h, z, yaw, pitch, roll, scale)), scale)
            for tpl, x, z, yaw, pitch, roll, scale, h in rows if tpl in SHEETS]


def edge_points(sheets, step=1.0):
    """Points along every sheet's four edges: (x, y, z) and which sheet."""
    out, owner = [], []
    for k, (tpl, m, scale) in enumerate(sheets):
        hw, hl = SHEETS[tpl]
        nl = max(2, int(math.ceil(2 * hl * scale / step)) + 1)
        nw = max(2, int(math.ceil(2 * hw * scale / step)) + 1)
        lz = np.linspace(-hl, hl, nl)
        lx = np.linspace(-hw, hw, nw)
        LX = np.r_[np.full(nl, -hw), np.full(nl, hw), lx, lx]
        LZ = np.r_[lz, lz, np.full(nw, -hl), np.full(nw, hl)]
        out.append(m[9:12][None, :] + LX[:, None] * m[0:3][None, :] + LZ[:, None] * m[6:9][None, :])
        owner.append(np.full(len(LX), k))
    return np.concatenate(out), np.concatenate(owner)


class PointGrid:
    """Points bucketed by 16 m square, for finding those under a sheet."""

    def __init__(self, xz, cell=16.0):
        self.cell = cell
        keys = (np.floor(xz[:, 0] / cell).astype(np.int64) << 20) + np.floor(xz[:, 1] / cell).astype(np.int64)
        self.order = np.argsort(keys, kind="stable")
        sk = keys[self.order]
        self.ukeys, self.starts = np.unique(sk, return_index=True)
        self.ends = np.r_[self.starts[1:], len(sk)]

    def in_box(self, x0, z0, x1, z1):
        res = []
        for a in range(int(math.floor(x0 / self.cell)), int(math.floor(x1 / self.cell)) + 1):
            lo = np.searchsorted(self.ukeys, (a << 20) + int(math.floor(z0 / self.cell)))
            hi = np.searchsorted(self.ukeys, (a << 20) + int(math.floor(z1 / self.cell)), side="right")
            for k in range(lo, hi):
                res.append(self.order[self.starts[k]:self.ends[k]])
        return np.concatenate(res) if res else np.zeros(0, np.int64)


def sheet_box(tpl, m):
    hw, hl = SHEETS[tpl]
    c = np.array([[sx * hw, sz * hl] for sx in (-1, 1) for sz in (-1, 1)])
    x = m[9] + c[:, 0] * m[0] + c[:, 1] * m[6]
    z = m[11] + c[:, 0] * m[2] + c[:, 1] * m[8]
    return x.min(), z.min(), x.max(), z.max()


def plan_coords(m, x, z):
    """Where points (seen from above) lie on a sheet: its model's x and z there."""
    dx, dz = x - m[9], z - m[11]
    ax, az = m[0], m[2]                              # the sheet's side, flat
    fx, fz = m[6], m[8]                              # its length, as seen from above
    return (dx * ax + dz * az) / (ax * ax + az * az), (dx * fx + dz * fz) / (fx * fx + fz * fz)


def under_sheets(sheets, xyz, owner=None, inner=0.95, tol=COVER_TOL):
    """Which points lie under another sheet's water (within `inner` of its half-width)
    whose surface there is at the point's height or higher (less `tol`)."""
    grid = PointGrid(xyz[:, [0, 2]])
    hit = np.zeros(len(xyz), bool)
    for k, (tpl, m, scale) in enumerate(sheets):
        idx = grid.in_box(*sheet_box(tpl, m))
        if not len(idx):
            continue
        if owner is not None:
            idx = idx[owner[idx] != k]
        hw, hl = SHEETS[tpl]
        lx, lz = plan_coords(m, xyz[idx, 0], xyz[idx, 2])
        ins = (np.abs(lx) <= inner * hw) & (np.abs(lz) <= hl + JOINT)
        sy = m[10] + lx * m[1] + lz * m[7]
        # Over a steep sheet a step is a little fall: allow more the steeper it is.
        step = tol + (STEP_PER_SLOPE * abs(m[7]) / scale if tol > 0 else 0.0)
        hit[idx[ins & (sy >= xyz[idx, 1] - step)]] = True
    return hit


def cell_weights(p, n, cell):
    """The four grid points of each point's cell, and their weights under each way of
    cutting the cell into triangles."""
    u, v = np.clip(p[:, 0] / cell, 0, n - 1.0001), np.clip(p[:, 2] / cell, 0, n - 1.0001)
    j, i = u.astype(int), v.astype(int)
    fx, fz = u - j, v - i
    nodes = [(i, j), (i, j + 1), (i + 1, j), (i + 1, j + 1)]
    lo = fx + fz <= 1
    wa = [np.where(lo, 1 - fx - fz, 0.0), np.where(lo, fx, 1 - fz), np.where(lo, fz, 1 - fx),
          np.where(lo, 0.0, fx + fz - 1)]
    lo = fx >= fz
    wb = [np.where(lo, 1 - fx, 1 - fz), np.where(lo, fx - fz, 0.0), np.where(lo, 0.0, fz - fx), np.where(lo, fz, fx)]
    return nodes, wa, wb


def middle_points(sheets, step=1.0):
    """Points along the middle of every stream and river sheet, away from its ends."""
    out = []
    for tpl, m, scale in sheets:
        if not tpl.startswith(("stream", "river")):
            continue
        hw, hl = SHEETS[tpl]
        mid = min(MID_HALF[tpl.split("_")[0]] / scale, 0.3 * hw)
        nl = max(2, int(math.ceil(2 * 0.85 * hl * scale / step)) + 1)
        lz = np.linspace(-0.85 * hl, 0.85 * hl, nl)
        LX = np.repeat([-mid, 0.0, mid], nl)
        LZ = np.tile(lz, 3)
        out.append(m[9:12][None, :] + LX[:, None] * m[0:3][None, :] + LZ[:, None] * m[6:9][None, :])
    return np.concatenate(out) if out else np.zeros((0, 3))


def nudge(elev, p, amount, fixed, up):
    """Move the free grid points of each point's cell by `amount` (divided by their
    weight, so the ground at the point moves by at least that much either way the cell
    is cut); per grid point the largest move asked for wins."""
    n = elev.shape[0]
    nodes, wa, wb = cell_weights(p, n, SIZE / n)
    free = [~fixed[ni, nj] for ni, nj in nodes]
    weight = np.minimum(sum(w * f for w, f in zip(wa, free)), sum(w * f for w, f in zip(wb, free)))
    ok = weight > 0.2                               # else the point sits on fixed ground: leave it
    move = np.where(ok, amount / np.maximum(weight, 0.2), 0.0)
    target = elev.copy()
    for (ni, nj), f in zip(nodes, free):
        m = ok & f
        if up:
            np.maximum.at(target, (ni[m], nj[m]), elev[ni[m], nj[m]] + move[m])
        else:
            np.minimum.at(target, (ni[m], nj[m]), elev[ni[m], nj[m]] - move[m])
    return target


def solve_ground(elev, sheets, protect, inner, base=None, rounds=ROUNDS, log=print):
    """Shape the ground under the sheets, round after round. Each grid point has one job:
    those under a channel (`inner`) only ever go down, until the ground along every stream
    and river sheet's middle lies VISIBLE under its water; the rest only ever go up, until
    every sheet edge is buried (unless another sheet's water covers it). So neither undoes
    the other and the rounds settle. Returns how many edge and middle points still fail."""
    edges, owner = edge_points(sheets)
    edges = edges[~under_sheets(sheets, edges, owner)]
    mids = middle_points(sheets)
    start = elev.copy() if base is None else base      # the caps count from here
    down_fixed = protect | ~inner
    up_fixed = protect | inner
    left_e = left_m = 0
    for r in range(rounds):
        a, b, _ = ground(elev, edges[:, 0], edges[:, 2])
        need = edges[:, 1] + EDGE_CLEAR - np.minimum(a, b)
        bad_e = need > 0
        left_e = int(bad_e.sum())
        if left_e:
            elev[:] = np.minimum(nudge(elev, edges[bad_e], need[bad_e], up_fixed, up=True),
                                 np.maximum(elev, start + MAX_RAISE))
        a, b, _ = ground(elev, mids[:, 0], mids[:, 2])
        over = np.maximum(a, b) - (mids[:, 1] - VISIBLE)
        bad_m = over > 0
        left_m = int(bad_m.sum())
        if left_m:
            elev[:] = np.maximum(nudge(elev, mids[bad_m], over[bad_m], down_fixed, up=False),
                                 np.minimum(elev, start - MAX_CUT))
        log("  round %d: %d of %d edge points under the water's level, %d of %d middle points with ground "
            "less than %.2f m under it" % (r + 1, left_e, len(edges), left_m, len(mids), VISIBLE))
        if not left_e and not left_m:
            break
    return left_e, left_m


# ---------------------------------------------------------------------- the last step

def read_rows(path):
    rows = []
    for line in open(path):
        p = line.strip().rstrip(";").split(";")
        if len(p) < 8:
            continue
        rows.append([p[0].strip('"')] + [float(v) for v in p[1:8]])
    return rows


def write_rows(path, rows):
    with open(path, "w", newline="\n") as fh:
        for r in rows:
            fh.write('"%s";%.3f;%.3f;%.3f;%.3f;%.3f;%.3f;%.3f;\n' % tuple(r))


def protected_ground(src, elev, water_elev):
    """Grid points the water mustn't touch: wherever the roads or building pads changed
    the ground after the water step, and every road's surface and levelled shoulders."""
    n = elev.shape[0]
    cell = SIZE / n
    changed = np.abs(elev - water_elev) > 0.01
    p = changed.copy()                                    # one grid point round, too
    p[1:] |= changed[:-1]
    p[:-1] |= changed[1:]
    p[:, 1:] |= changed[:, :-1]
    p[:, :-1] |= changed[:, 1:]
    flat = p.ravel()
    for rd in json.load(open(os.path.join(src, "roads", "centerlines.json"))):
        pts = np.asarray(rd["points"], float)[:, :2]
        if len(pts) < 2:
            continue
        seg = np.hypot(*np.diff(pts, axis=0).T)
        dense = [pts[0]]
        for a, b, l in zip(pts[:-1], pts[1:], seg):
            k = max(1, int(math.ceil(l / 2.0)))
            dense += [a + (b - a) * t for t in np.arange(1, k + 1) / k]
        key, d, _ = nodes_near_points(np.asarray(dense), ROAD_HALF.get(rd["family"], 3.5) + ROAD_SHOULDER, cell, n)
        flat[key] = True
    return p


def object_in_water(sheets, xz, elev):
    """Objects standing where the ground lies under a sheet's water."""
    g = bilinear(elev, xz[:, 0], xz[:, 1])
    xyz = np.c_[xz[:, 0], g, xz[:, 1]]
    return under_sheets(sheets, xyz, None, inner=1.0, tol=-0.05)


def nodes_under(sheets, shape):
    """Grid points under any sheet."""
    n = shape[0]
    cell = SIZE / n
    under = np.zeros(shape, bool)
    for tpl, m, scale in sheets:
        x0, z0, x1, z1 = sheet_box(tpl, m)
        i0, i1 = max(0, int(z0 / cell)), min(n - 1, int(z1 / cell) + 1)
        j0, j1 = max(0, int(x0 / cell)), min(n - 1, int(x1 / cell) + 1)
        ii, jj = np.mgrid[i0:i1 + 1, j0:j1 + 1]
        lx, lz = plan_coords(m, jj.ravel() * cell, ii.ravel() * cell)
        hw, hl = SHEETS[tpl]
        ins = (np.abs(lx) <= hw) & (np.abs(lz) <= hl)
        under[ii.ravel()[ins], jj.ravel()[ins]] = True
    return under


def touches(mask, p):
    """Do the points' cells have a grid point in mask?"""
    n = mask.shape[0]
    nodes, _, _ = cell_weights(p, n, SIZE / n)
    t = np.zeros(len(p), bool)
    for ni, nj in nodes:
        t |= mask[ni, nj]
    return t


def hanging_at_roads(elev, rows, mask, cover=True):
    """Indices of the rows (sheets) with an edge hanging more than CULVERT_HANG over
    ground the roads or building pads shaped, not under other water."""
    idx = [k for k, r in enumerate(rows) if r[0] in SHEETS]
    if not idx:
        return set()
    sh = sheet_transforms([rows[k] for k in idx])
    pts, owner = edge_points(sh)
    cov = under_sheets(sh, pts, owner) if cover else np.zeros(len(pts), bool)
    a, b, _ = ground(elev, pts[:, 0], pts[:, 2])
    bad = (pts[:, 1] - np.minimum(a, b) > CULVERT_HANG) & ~cov & touches(mask, pts)
    return {idx[o] for o in np.unique(owner[bad])}


def shorter(row):
    """The same water as shorter pieces (a creek piece in 12 or 6 m lengths, a pond tile
    in quarters), each list one way of cutting it; the shortest last."""
    tpl, x, z, yaw, pitch, roll, scale, h = row
    ways = []
    if tpl.startswith(("stream", "river")):
        base, length = "_".join(tpl.split("_")[:2]), float(tpl.split("_")[-1])
        a, b = math.radians(yaw), math.radians(pitch)
        for sub in (12.0, 6.0):
            if sub >= length:
                continue
            pieces = []
            for off in np.arange(-length / 2 + sub / 2, length / 2 - sub / 2 + 1e-6, sub) * scale:
                horiz = off * math.cos(b)
                pieces.append(["%s_%d" % (base, sub), x + horiz * math.sin(a), z + horiz * math.cos(a), yaw, pitch,
                               roll, scale, h - off * math.sin(b)])
            ways.append(pieces)
    elif tpl == "pond_50x50" and scale >= 0.2:
        a = math.radians(yaw)
        ax, az = (math.cos(a), -math.sin(a)), (math.sin(a), math.cos(a))
        q = 25.0 * scale / 2
        ways.append([[tpl, x + (i * ax[0] + j * az[0]) * q, z + (i * ax[1] + j * az[1]) * q, yaw, pitch, roll,
                      scale / 2, h] for i in (-1, 1) for j in (-1, 1)])
    return ways


def drop_hanging(elev, rows):
    """Leave out the sheets whose edges hang more than DROP_HANG, not under other water;
    again until none do (leaving one out can bare its neighbours' ends)."""
    rows = [list(r) for r in rows]
    total = 0
    for _ in range(4):
        idx = [k for k, r in enumerate(rows) if r[0] in SHEETS]
        sh = sheet_transforms([rows[k] for k in idx])
        pts, owner = edge_points(sh)
        cov = under_sheets(sh, pts, owner)
        a, b, _ = ground(elev, pts[:, 0], pts[:, 2])
        bad = {idx[o] for o in np.unique(owner[(pts[:, 1] - np.minimum(a, b) > DROP_HANG) & ~cov])}
        if not bad:
            break
        rows = [r for k, r in enumerate(rows) if k not in bad]
        total += len(bad)
    return rows, total


def cut_at_roads(elev, rows, mask, log):
    """Where water reaches a road or a building pad hanging over its ground (a creek into
    a road cut, a pond against a fill), stop it short, as a culvert: cut those pieces
    into shorter ones and keep those that don't hang there; leave the rest out."""
    rows = [list(r) for r in rows]
    cut = dropped = 0
    for _ in range(4):
        bad = hanging_at_roads(elev, rows, mask)
        if not bad:
            break
        out = []
        for k, r in enumerate(rows):
            if k not in bad:
                out.append(r)
                continue
            kept = None
            for pieces in shorter(r):
                clean = [pieces[i] for i in range(len(pieces))
                         if i not in hanging_at_roads(elev, pieces, mask, cover=False)]
                if clean:
                    kept = clean
                    break
            if kept:
                out.extend(kept)
                cut += 1
            else:
                dropped += 1
        rows = out
    log("water reaching roads and pads (culverts): %d pieces cut shorter, %d left out" % (cut, dropped))
    return rows


def main():
    src = sys.argv[1]
    log_lines = []

    def log(s):
        print(s, flush=True)
        log_lines.append(s)
    final_path = os.path.join(src, "buildings", "elevation.npy")
    stamp_path = os.path.join(src, "water", "fit_stamp.json")
    digest = hashlib.md5(open(final_path, "rb").read()).hexdigest()
    if os.path.exists(stamp_path) and json.load(open(stamp_path)).get("wrote") == digest:
        sys.exit("%s is this step's own output: it would adjust the object lists twice. Rerun the chain from "
                 "tools/buildings.py on (it rewrites the heights), then this." % final_path)
    elev = np.load(final_path).astype(np.float64)
    old = elev.copy()
    water_elev = np.load(os.path.join(src, "water", "elevation.npy")).astype(np.float64)
    channels = json.load(open(os.path.join(src, "water", "channels.json")))
    wrows = json.load(open(os.path.join(src, "water", "water_roads_abs.json")))
    protect = protected_ground(src, elev, water_elev)
    log("protected grid points (roads, pads): %d" % int(protect.sum()))

    bed, bank, _ = channel_targets(elev.shape, channels)
    inner = apply_targets(elev, bed, bank, protect)
    sheets = sheet_transforms(wrows)
    solve_ground(elev, sheets, protect, inner, base=old, log=log)
    moved = np.abs(elev - old) > 0.01
    log("ground changed at %d grid points: raised %d (max %.2f m), lowered %d (max %.2f m)"
        % (int(moved.sum()), int((elev - old > 0.01).sum()), float((elev - old).max()),
           int((old - elev > 0.01).sum()), float((old - elev).max())))
    wrows = cut_at_roads(elev, wrows, np.abs(old - water_elev) > 0.01, log)
    sheets = sheet_transforms(wrows)
    # The channel past where cut water now stops (towards a culvert) is no bed any more:
    # let it rise, so the water's new end lies on ground, and solve once more.
    log("again, with the channels the water no longer reaches free to rise:")
    solve_ground(elev, sheets, protect, inner & nodes_under(sheets, elev.shape), base=old, log=log)
    # Water that still hangs a long way (a pond's dam over a steep fall, a cascade over a
    # cliff step: more than the ground may be raised) is better left out than floating.
    wrows, n_drop = drop_hanging(elev, wrows)
    sheets = sheet_transforms(wrows)
    log("pieces still hanging more than %.1f m, left out: %d; once more:" % (DROP_HANG, n_drop))
    solve_ground(elev, sheets, protect, inner & nodes_under(sheets, elev.shape), base=old, log=log)
    np.save(final_path, elev.astype(np.float32))
    json.dump({"wrote": hashlib.md5(open(final_path, "rb").read()).hexdigest()}, open(stamp_path, "w"))

    # The water keeps its heights, relative to the new ground.
    with open(os.path.join(src, "water", "tb_water.txt"), "w", newline="\n") as fh:
        for tpl, x, z, yaw, pitch, roll, scale, absolute in wrows:
            rel = absolute - float(bilinear(elev, x, z))
            fh.write('"%s";%.3f;%.3f;%.3f;%.3f;%.3f;%.3f;%.3f;\n' % (tpl, x + EASTING, z, yaw, pitch, roll, scale, rel))

    # Everything else: keep heights, or follow the ground and leave the water.
    for rel_path in KEEP_HEIGHT:
        path = os.path.join(src, rel_path)
        if not os.path.exists(path):
            continue
        rows = read_rows(path)
        if not rows:
            continue
        xz = np.array([(r[1] - EASTING, r[2]) for r in rows])
        delta = bilinear(elev, xz[:, 0], xz[:, 1]) - bilinear(old, xz[:, 0], xz[:, 1])
        changed = np.abs(delta) > 0.001
        for k in np.nonzero(changed)[0]:
            rows[k][7] -= delta[k]
        if changed.any():
            write_rows(path, rows)
        log("%-28s %6d objects, %d kept at their height over changed ground" % (rel_path, len(rows), int(changed.sum())))
    for rel_path in FOLLOW_GROUND:
        path = os.path.join(src, rel_path)
        if not os.path.exists(path):
            continue
        rows = read_rows(path)
        xz = np.array([(r[1] - EASTING, r[2]) for r in rows])
        wet = object_in_water(sheets, xz, elev)
        if wet.any():
            write_rows(path, [r for r, w in zip(rows, wet) if not w])
        log("%-28s %7d objects, %d taken out of the water" % (rel_path, len(rows), int(wet.sum())))

    r = check(elev, [tuple([w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7] - float(bilinear(elev, w[1], w[2]))])
                     for w in wrows if w[0] in SHEETS])
    log("check: %d water sheets; edge points hanging over 5 cm, not under other water: %d of %d (%.2f%%), "
        "over 0.25 / 0.5 / 1 m: %d / %d / %d; middle points with ground over the water: %d of %d (%.2f%%)"
        % (r["sheets"], r["hanging_samples"], r["edge_samples"], 100.0 * r["hanging_samples"] / max(1, r["edge_samples"]),
           r["hang_over"][0.25], r["hang_over"][0.5], r["hang_over"][1.0], r["poking_samples"], r["mid_samples"],
           100.0 * r["poking_samples"] / max(1, r["mid_samples"])))
    log("worst remaining (m, model, x, z): %s" % r["worst"][:10])
    with open(os.path.join(src, "water", "fit_summary.txt"), "w", newline="\n") as fh:
        fh.write("Water fitted to the final ground (tools/water_fit.py)\n\n" + "\n".join(log_lines) + "\n")


if __name__ == "__main__":
    main()
