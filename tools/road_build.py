"""Build the roads from straight and curve parts joined end to end, carve the ground
under them, and lay the trails on the ground.

    python tools/road_build.py source/water/elevation.npy source

Reads source/roads/lines.json (tools/osm_roads.py), source/water/lines.json and
source/water/water_abs.json (tools/osm_water.py). Writes:
  source/roads/tb_roads_main.txt, tb_roads_local.txt, tb_trails.txt   the parts
  source/roads/centerlines.json   every road as built: centreline points (x, z, height)
  source/roads/elevation.npy      the heights with the roads carved in
  source/water/tb_water.txt       the water, rewritten relative to the carved ground
  source/roads/build_summary.txt

Roads are built as Terrain Builder's road tool builds them: from the vanilla
straight parts (25, 12.5, 6.25 m) and curve parts (0.5 to 60 degree arcs, 10 to
2000 m radius), each starting exactly where the last one ends, so no joint opens.
Every part's start is its model's origin and curves turn right (left turns are
the same part laid the other way round); 95-97% of vanilla Chernarus's part ends
meet another part's end this way. The parts follow OpenStreetMap's line within
TOL metres, choosing the longest part that keeps the next one in tolerance too.
Ways that simply continue one another are joined first, so a road's curve isn't
broken where OSM splits it. Dead ends get the family's end cap (*_6konec).

Heights: the ground along each road (averaged across its width) is smoothed
along it, and every part is pitched to that profile, so ends meet in height as
well. The ground is then carved to the parts: level across the road out to
CORE metres beyond its edge (the terrain grid is 5 m, so the triangles under
the road must be flat too), then back to the natural ground over a bank at
most 1:1.2 steep. Roads are built in order of class (asf1 first); a lesser road
joining a greater one takes its height at the junction and never cuts into it.
Creek channels are left alone outside a road's own surface, so culverts stay.

Trails (path_dirt_10, path_rock_10 on steep ground) are 10 m parts chained along
their line and pitched and rolled to lie on the ground.
"""

import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter1d
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import bilinear  # noqa: E402
from odol_info import odol_info  # noqa: E402
from osm_roads import chain  # noqa: E402

SIZE = 20480.0
EASTING = 200000.0
PARTS = r"P:\DZ\structures\roads\parts"
# family -> (width m, smoothing sigma m, follow tolerance m, lift above the carved ground m)
FAMILIES = {
    "asf1": (12.0, 14.0, 0.6, 0.06),
    "asf2": (9.0, 12.0, 0.6, 0.05),
    "asf3": (7.0, 10.0, 0.6, 0.04),
    "grav": (6.0, 8.0, 0.8, 0.03),
    "mud": (5.0, 8.0, 0.9, 0.02),
}
JUNCTION_DROP = 0.015            # a road's parts on another road's surface sit this much lower
HAIRPIN_TURN, HAIRPIN_SPAN = 100.0, 30.0   # turning this many degrees within this many metres: flat
PIN_SIGMA = 25.0                 # how far a junction's height reaches along the joining road
MAX_GRADE = {"asf1": 0.30, "asf2": 0.30, "asf3": 0.40, "grav": 0.45, "mud": 0.45}   # spikes only
HAIRPIN_TOL = 3.0                # extra freedom from the OSM line through a switchback turn
SHARP_TURN = 35.0                # turning this many degrees within 6 m: a sharp corner, one grade
LEVEL_REACH = 8.0                # one grade this far either side of a sharp joint


def zone_profile(prof, level, locked, hair, ds=2.0):
    """The profile made straight (one grade) over each run of `level` samples, eased in
    and out, junction pins kept; and its grade wherever that or a switchback turn
    lies (NaN elsewhere): where a part ending there should arrive at."""
    out = prof.copy()
    runs = []
    if level.any():
        # each run straight from the profile at its first sample to its last (so the
        # profile carries on unbroken at both ends, only its grade changes there)
        edges = np.flatnonzero(np.diff(np.r_[0, level.astype(int), 0]))
        for a, b in zip(edges[::2], edges[1::2]):
            g = (prof[b - 1] - prof[a]) / ((b - 1 - a) * ds) if b - a >= 2 else 0.0
            runs.append((a, b, g, prof[a] - g * a * ds))
        for a, b, g, c in runs:
            out[a:b] = c + g * np.arange(a, b) * ds
        out = np.where(locked, prof, out)
    zone = (level | hair) & ~locked              # (a pinned height is no part of one)
    slope = np.where(zone, np.gradient(out, ds) if len(out) > 1 else 0.0, np.nan)
    for a, b, g, c in runs:
        slope[a:b] = np.where(zone[a:b], g, np.nan)
    return out, slope


def limit_grade(prof, ds, g, fixed):
    """Keep a profile's slope under g (rise over run, samples ds apart), holding the
    fixed samples (junction pins) where they are."""
    prof = prof.copy()
    step = g * ds
    for _ in range(60):
        before = prof.copy()
        for i in range(1, len(prof)):
            prof[i] = min(max(prof[i], prof[i - 1] - step), prof[i - 1] + step) if not fixed[i] else prof[i]
        for i in range(len(prof) - 2, -1, -1):
            prof[i] = min(max(prof[i], prof[i + 1] - step), prof[i + 1] + step) if not fixed[i] else prof[i]
        if np.abs(prof - before).max() < 1e-4:
            break
    return prof
ORDER = ["asf1", "asf2", "asf3", "grav", "mud"]
STRAIGHTS = [(25.0, "_25"), (12.5, "_12"), (6.25, "_6")]
ARCS = [(0.5, 2000.0, "_0 2000"), (1.0, 1000.0, "_1 1000"), (7.5, 100.0, "_7 100"), (10.0, 100.0, "_10 100"),
        (10.0, 75.0, "_10 75"), (15.0, 75.0, "_15 75"), (10.0, 50.0, "_10 50"), (22.5, 50.0, "_22 50"),
        (10.0, 25.0, "_10 25"), (30.0, 25.0, "_30 25"), (60.0, 10.0, "_60 10")]
KONEC = ("_6konec", 6.25)
CORE = 6.0                       # level ground this far beyond the road's edge
HARD = 2.5                       # the nearest of it no lesser road may change
SOFT = 0.995                     # (the rest a lesser road's own level ground may take over)
BANK_MIN, BANK_SLOPE, BANK_MAX = 6.0, 1.2, 25.0
STEP = 0.25                      # resampling of the OSM line
SMOOTH = 3.0                     # and the rounding of its corners (sigma, m)
TRAIL, TRAIL_ROCK, TRAIL_LEN, TRAIL_W = "path_dirt_10", "path_rock_10", 10.0, 2.35
ROCK_SLOPE = 0.7
TRAIL_LIFT = 0.04
JOIN = 0.6                       # endpoints this close are the same node


# ------------------------------------------------------------------ geometry

def d_of(psi):
    return np.array([math.sin(psi), math.cos(psi)])


def r_of(psi):
    return np.array([math.cos(psi), -math.sin(psi)])


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class Shape:
    """A part's travel geometry: forward and lateral offsets of its centreline (unpitched)."""

    def __init__(self, name, kind, length=0.0, angle=0.0, radius=0.0, side=0):
        self.name, self.kind, self.side = name, kind, side
        if kind == "straight":
            self.fwd, self.lat, self.turn, self.arclen = length, 0.0, 0.0, length
            t = np.linspace(0, 1, max(3, int(length / 2) + 1))
            self.samples = np.c_[t * length, np.zeros_like(t)]
        else:
            a = math.radians(angle)
            self.a, self.R = a, radius
            self.fwd, self.lat = radius * math.sin(a), side * radius * (1 - math.cos(a))
            self.turn, self.arclen = side * a, radius * a
            t = np.linspace(0, a, max(3, int(radius * a / 2) + 1))
            self.samples = np.c_[radius * np.sin(t), side * radius * (1 - np.cos(t))]

    def world(self, X, psi, pts=None):
        p = self.samples if pts is None else pts
        return X + np.outer(p[:, 0], d_of(psi)) + np.outer(p[:, 1], r_of(psi))


def model_centre(name):
    info = odol_info(os.path.join(PARTS, name + ".p3d"))
    if info is None:
        sys.exit("missing road part model " + name)
    return np.array(info["center"])


def place_piece(shape, X, h, psi, phi):
    """Lay a part from travel point X (height h, heading psi) pitched by phi (up, along
    travel). Returns (end point, end height, end heading, model start, model start
    height, model heading, model pitch)."""
    if shape.kind == "straight" or shape.side > 0:
        th, psim, S, hs = phi, psi, X, h
        if shape.kind == "straight":
            E = X + d_of(psi) * shape.fwd * math.cos(th)
            psi_end = psi
        else:
            a, R = shape.a, shape.R
            E = X + r_of(psi) * R * (1 - math.cos(a)) + d_of(psi) * R * math.sin(a) * math.cos(th)
            psi_end = psi + math.atan2(math.sin(a), math.cos(a) * math.cos(th))
        hE = h + shape.fwd * math.sin(th)
        return E, hE, psi_end, S, hs, psim, th
    # Left turn: the right-turning model laid backwards, its end at X.
    a, R = shape.a, shape.R
    th = -phi
    beta = math.atan2(math.sin(a), math.cos(a) * math.cos(th))
    psim = psi + math.pi - beta
    delta = r_of(psim) * R * (1 - math.cos(a)) + d_of(psim) * R * math.sin(a) * math.cos(th)
    S = X - delta
    hs = h - R * math.sin(a) * math.sin(th)
    return S, hs, psi - beta, S, hs, psim, th


# ------------------------------------------------------------------ lines

def densify(points, step):
    pts = np.asarray(points, float)
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.ceil(np.hypot(*(b - a)) / step)))
        for k in range(1, n + 1):
            out.append(a + (b - a) * k / n)
    out = np.array(out)
    keep = np.r_[True, np.hypot(*np.diff(out, axis=0).T) > 1e-6]
    return out[keep]


def smooth_line(poly, sigma):
    """Round a STEP-resampled line's corners (OSM kinks at every node; roads curve),
    holding its ends where they are so junctions still meet."""
    if len(poly) < 8:
        return poly
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(poly, axis=0).T))]
    sm = np.c_[gaussian_filter1d(poly[:, 0], sigma / STEP, mode="nearest"),
               gaussian_filter1d(poly[:, 1], sigma / STEP, mode="nearest")]
    w = np.clip(s / (3 * sigma), 0, 1) * np.clip((s[-1] - s) / (3 * sigma), 0, 1)
    out = sm * w[:, None] + poly * (1 - w[:, None])
    return densify(out, STEP)


def stitch(lines, key):
    """Join lines that continue one another: an endpoint shared by exactly two lines
    with the same key. Returns new line dicts (points joined, other fields of the first)."""
    nodes = {}
    for i, ln in enumerate(lines):
        for end in (0, -1):
            p = ln["points"][end]
            nodes.setdefault((round(p[0] / JOIN), round(p[1] / JOIN)), []).append((i, end))
    nbr = {}
    for ends in nodes.values():
        if len(ends) == 2 and ends[0][0] != ends[1][0]:
            (i, ei), (j, ej) = ends
            if key(lines[i]) == key(lines[j]):
                nbr[(i, ei)] = (j, ej)
                nbr[(j, ej)] = (i, ei)
    used, out = set(), []
    for i in range(len(lines)):
        if i in used:
            continue
        # walk back to a chain's start
        cur, end = i, 0
        seen = {i}
        while (cur, end) in nbr:
            j, ej = nbr[(cur, end)]
            if j in seen:
                break
            seen.add(j)
            cur, end = j, (-1 if ej == 0 else 0)
        start, start_end = cur, end
        pts = []
        cur, entry = start, start_end
        while True:
            used.add(cur)
            seq = lines[cur]["points"] if entry == 0 else lines[cur]["points"][::-1]
            pts.extend(seq if not pts else seq[1:])
            exit_end = -1 if entry == 0 else 0
            if (cur, exit_end) not in nbr:
                break
            j, ej = nbr[(cur, exit_end)]
            if j in used:
                break
            cur, entry = j, ej
        ln = dict(lines[start])
        ln["points"] = [list(map(float, p)) for p in pts]
        out.append(ln)
    return out


# ------------------------------------------------------------------ the builder

class Ground:
    def __init__(self, nat, water_keep):
        self.nat = nat.astype(np.float64)
        self.cell = SIZE / nat.shape[0]
        self.W = np.zeros(nat.shape, np.float32)
        self.T = np.zeros(nat.shape, np.float64)
        self.water = water_keep

    def current(self):
        return self.W * self.T + (1 - self.W) * self.nat

    def h(self, grid, x, z):
        return bilinear(grid, x / self.cell, z / self.cell)

    def h_many(self, grid, x, z):
        gx, gz = np.asarray(x) / self.cell, np.asarray(z) / self.cell
        n = grid.shape[0]
        x0 = np.clip(np.floor(gx).astype(int), 0, n - 2)
        z0 = np.clip(np.floor(gz).astype(int), 0, n - 2)
        fx, fz = np.clip(gx - x0, 0, 1), np.clip(gz - z0, 0, 1)
        return (grid[z0, x0] * (1 - fx) * (1 - fz) + grid[z0, x0 + 1] * fx * (1 - fz)
                + grid[z0 + 1, x0] * (1 - fx) * fz + grid[z0 + 1, x0 + 1] * fx * fz)

    def cur_many(self, x, z):
        """The ground as carved so far, at points (bilinear over the four nodes)."""
        gx, gz = np.asarray(x, float) / self.cell, np.asarray(z, float) / self.cell
        n = self.nat.shape[0]
        x0 = np.clip(np.floor(gx).astype(int), 0, n - 2)
        z0 = np.clip(np.floor(gz).astype(int), 0, n - 2)
        fx, fz = np.clip(gx - x0, 0, 1), np.clip(gz - z0, 0, 1)

        def at(i, j):
            w = self.W[i, j]
            return w * self.T[i, j] + (1 - w) * self.nat[i, j]
        return (at(z0, x0) * (1 - fx) * (1 - fz) + at(z0, x0 + 1) * fx * (1 - fz)
                + at(z0 + 1, x0) * (1 - fx) * fz + at(z0 + 1, x0 + 1) * fx * fz)

    def locked_many(self, x, z):
        i = np.clip(np.round(np.asarray(z) / self.cell).astype(int), 0, self.W.shape[0] - 1)
        j = np.clip(np.round(np.asarray(x) / self.cell).astype(int), 0, self.W.shape[1] - 1)
        return self.W[i, j] >= 0.999

    def carve(self, cl, cl_h, half):
        """Carve to a road's centreline samples cl (N x 2) with heights cl_h."""
        # every 0.5 m, so a point near the edge takes the height right beside it
        seg = np.hypot(*np.diff(cl, axis=0).T)
        s = np.r_[0, np.cumsum(seg)]
        keep = np.r_[True, seg > 1e-6]
        s, cl, cl_h = s[keep], cl[keep], cl_h[keep]
        fine = np.arange(0, s[-1] + 1e-6, 0.5)
        cl = np.c_[np.interp(fine, s, cl[:, 0]), np.interp(fine, s, cl[:, 1])]
        cl_h = np.interp(fine, s, cl_h)
        rc = half + CORE
        reach = rc + BANK_MAX
        x0, z0 = cl.min(axis=0) - reach
        x1, z1 = cl.max(axis=0) + reach
        n = self.nat.shape[0]
        j0, j1 = max(0, int(x0 / self.cell)), min(n - 1, int(x1 / self.cell) + 1)
        i0, i1 = max(0, int(z0 / self.cell)), min(n - 1, int(z1 / self.cell) + 1)
        jj, ii = np.meshgrid(np.arange(j0, j1 + 1), np.arange(i0, i1 + 1))
        gx, gz = jj * self.cell, ii * self.cell
        # Nearest distance and height from every 40 m stretch of the road. Next to the
        # road its own height holds; further out, where another stretch passes close
        # (the next leg of a switchback), heights blend by inverse distance, so the
        # bank between them is a ramp, not a step on the 5 m grid.
        V = np.c_[gx.ravel(), gz.ravel()]
        dmin = np.full(len(V), np.inf)
        hmin = np.zeros(len(V))
        sw = np.zeros(len(V))
        swh = np.zeros(len(V))
        edge = half + HARD
        for c0 in np.arange(0, len(cl), 80):
            seg_pts = cl[c0:c0 + 81]
            seg_h = cl_h[c0:c0 + 81]
            lo = seg_pts.min(axis=0) - reach
            hi = seg_pts.max(axis=0) + reach
            sel = np.where((V[:, 0] >= lo[0]) & (V[:, 0] <= hi[0]) & (V[:, 1] >= lo[1]) & (V[:, 1] <= hi[1]))[0]
            if not len(sel):
                continue
            dd, kk = cKDTree(seg_pts).query(V[sel], distance_upper_bound=reach)
            okk = np.isfinite(dd)
            sel, dd, hh = sel[okk], dd[okk], seg_h[kk[okk]]
            closer = dd < dmin[sel]
            dmin[sel[closer]] = dd[closer]
            hmin[sel[closer]] = hh[closer]
            wgt = 1.0 / np.maximum(dd - edge, 0.5) ** 2
            np.add.at(sw, sel, wgt)
            np.add.at(swh, sel, wgt * hh)
        ok = np.isfinite(dmin)
        blend = np.where(sw > 0, swh / np.maximum(sw, 1e-12), hmin)
        target = np.where(dmin <= edge, hmin, blend).reshape(gx.shape)
        d = np.where(ok, dmin, reach).reshape(gx.shape)
        nat = self.nat[ii, jj]
        bank = np.clip(BANK_MIN + BANK_SLOPE * np.abs(target - nat), BANK_MIN, BANK_MAX)
        t = np.clip((d - rc) / bank, 0, 1)
        w = np.where(d <= rc, SOFT, (1 - t * t * (3 - 2 * t)) * SOFT)
        w = np.where(d <= half + HARD, 1.0, w)
        w = np.where(ok.reshape(gx.shape), w, 0.0)
        w = np.where(self.water[ii, jj] & (d > half + 1.0), 0.0, w)
        sub_w = self.W[ii, jj]
        better = w > sub_w + 1e-6
        self.W[ii, jj] = np.where(better, w, sub_w).astype(np.float32)
        self.T[ii, jj] = np.where(better, target, self.T[ii, jj])


def follow(poly, s_poly, tangent, prof_s, prof_h, shapes, tol, start_psi, end_mode, start_cap, cap_shape,
           surface=None, max_grade=0.25, tol_s=None, zones=None):
    """Chain parts along a polyline (STEP-resampled). Each step weighs every part
    followed by every part (two ahead): how far they stray from the line, the
    heading left at the end, and how far they get; only the first is laid.
    Returns the parts and the centreline samples (x, z, h)."""
    tree = cKDTree(poly)
    total = s_poly[-1]
    n_sh = len(shapes)
    stack = np.vstack([sh.samples for sh in shapes])
    sizes = [len(sh.samples) for sh in shapes]
    starts = np.r_[0, np.cumsum(sizes)[:-1]]
    last_idx = np.cumsum(sizes) - 1
    turns = np.array([sh.turn for sh in shapes])
    fwds = np.array([sh.fwd for sh in shapes])
    sides = np.sign(turns)
    arc_cos = np.array([math.cos(sh.a) if sh.kind == "arc" else 1.0 for sh in shapes])

    def prof(s):
        return float(np.interp(s, prof_s, prof_h))

    def nearest_s(pts, s_lo, s_hi):
        dd, kk = tree.query(pts, k=8, distance_upper_bound=40.0)
        valid = np.isfinite(dd)
        kk = np.where(valid, kk, 0)
        ss = s_poly[kk]
        valid &= (ss >= s_lo) & (ss <= s_hi)
        dd = np.where(valid, dd, 99.0)
        best = dd.argmin(axis=1)
        rows = np.arange(len(pts))
        return dd[rows, best], np.where(dd[rows, best] < 99, ss[rows, best], -1.0)

    def eval_from(Xs, psis, s_lo, s_hi):
        """Every part from every start state: (deviation, end progress, end heading
        error, end point, end heading), each M x n_sh."""
        d = np.stack([np.sin(psis), np.cos(psis)], 1)
        r = np.stack([np.cos(psis), -np.sin(psis)], 1)
        P = Xs[:, None, :] + stack[None, :, 0:1] * d[:, None, :] + stack[None, :, 1:2] * r[:, None, :]
        dd, ss = nearest_s(P.reshape(-1, 2), s_lo, s_hi)
        dd = dd.reshape(len(Xs), -1)
        ss = ss.reshape(len(Xs), -1)
        dev = np.maximum.reduceat(dd, starts, axis=1)
        s_end = ss[:, last_idx]
        psi_end = psis[:, None] + turns[None, :]
        k = np.clip(np.searchsorted(s_poly, s_end), 0, len(s_poly) - 1)
        herr = np.abs((psi_end - tangent[k] + math.pi) % (2 * math.pi) - math.pi)
        herr = np.where(s_end >= 0, herr, math.pi)
        return dev, s_end, herr, P[:, last_idx, :], psi_end

    parts, cl = [], []
    anchors = []          # where the road had to take a sharp joint (along the line)
    covers_cl = []        # each short part across a joint: its index and its centreline samples
    X, psi = poly[0].copy(), start_psi
    h = prof(0.0)
    s_cur = 0.0

    # the profile's grade round sharp joints and switchback turns (NaN elsewhere)
    z_slope = zones if zones is not None else np.full(len(prof_s), np.nan)

    def zone_k(s):
        """Index of the profile sample at s, or -1 if s is in no such stretch."""
        k = np.clip(np.rint(np.asarray(s, float) / 2.0).astype(int), 0, len(prof_s) - 1)
        return np.where(np.isnan(z_slope[k]), -1, k)

    last_g = [0.0]        # grade of the last real part laid
    carry = [None]        # after a sharp joint: the grade the next part keeps

    def lay(shape, X, h, psi, s_target, h_target=None, grade=None):
        fwd = shape.fwd
        # A part's surface is a plane sloping along its model's axis: a right curve's
        # start heading, a left curve's end heading (the model laid backwards). Along
        # the other end's heading the grade is cos(angle) of that.
        arc_cos = math.cos(shape.a) if shape.kind == "arc" else 1.0
        if grade is not None:
            phi = math.atan(max(-0.55, min(0.55, grade / (arc_cos if shape.side < 0 else 1.0))))
        else:
            goal = prof(s_target) if h_target is None else h_target
            phi = math.asin(max(-0.5, min(0.5, (goal - h) / fwd)))
        E, hE, psi_end, S, hs, psim, th = place_piece(shape, X, h, psi, phi)
        parts.append((shape.name, S, hs, psim, th))
        last_g[0] = math.tan(phi) * (arc_cos if shape.side > 0 else 1.0)    # the grade it ends on
        # centreline samples along the travel path, heights linear in forward distance
        pts = shape.world(X, psi)
        f = shape.samples[:, 0] / max(fwd, 1e-6)
        for p, fr in zip(pts, f):
            cl.append((p[0], p[1], h + (hE - h) * fr))
        return E, hE, psi_end

    cover = next(sh for sh in shapes if sh.kind == "straight" and abs(sh.fwd - 6.25) < 1e-6)

    def reanchor(X, h, psi, s_cur):
        # a few metres on at most: near a switchback's apex the nearest point of the
        # line can be on the other leg
        s_proj = float(nearest_s(X[None], s_cur - 3.0, s_cur + 5.0)[1][0])
        s_new = min(total, max(s_cur, s_proj) + 1.0)
        k = int(np.clip(np.searchsorted(s_poly, s_new), 0, len(s_poly) - 1))
        Xn, psin = poly[k].copy(), float(tangent[k])
        mid = (X + Xn) / 2
        bis = psi + wrap(psin - psi) / 2
        # The road keeps the grade it came in with across the joint: the part after it
        # starts that much higher and climbs as the part before did, so the short part
        # across the joint lies on both (a change of grade goes to an ordinary joint,
        # where the ends meet exactly).
        g = max(-max_grade, min(max_grade, last_g[0]))
        h_new = h + g * float((Xn - X) @ d_of(bis))       # how far on it is along the way (not aside)
        carry[0] = g
        phi = math.atan(g)
        half_c = cover.fwd / 2
        hm = (h + h_new) / 2
        start = mid - d_of(bis) * half_c * math.cos(phi)
        E, hE, psi_e, S, hs, psim, th = place_piece(cover, start, hm - half_c * math.sin(phi), bis, phi)
        parts.append(("COVER:" + cover.name, S, hs, psim, th))
        tip_b = mid - d_of(bis) * half_c
        tip_f = mid + d_of(bis) * half_c
        first = len(cl)
        for p, hh in ((X, h), (tip_b, hm - half_c * math.tan(phi)), (mid, hm), (tip_f, hm + half_c * math.tan(phi)),
                      (Xn, h_new)):
            cl.append((p[0], p[1], hh))
        covers_cl.append((len(parts) - 1, list(range(first, len(cl)))))
        anchors.append((s_cur + s_new) / 2)
        return Xn, h_new, psin, s_new

    if start_cap is not None:
        E, hE, psi_e = lay(start_cap, X, h, psi, min(total, start_cap.fwd))
        X, h, psi = E, hE, psi_e
        s_cur = float(nearest_s(X[None], -1, total + 1)[1][0])

    guard = 0
    while guard < 100000:
        guard += 1
        remaining = total - s_cur
        if remaining < 6.3:
            kind, other_half = end_mode
            last = next(sh for sh in shapes if sh.kind == "straight" and abs(sh.fwd - 6.25) < 1e-6)
            # (just past a sharp joint the last part too keeps the grade it came in with)
            if kind == "dead":
                # a dead end always gets its cap; the cap's faded end is its model origin,
                # laid so it ends at the line's end
                lay(cap_shape, X, h, psi, total, grade=carry[0])
                parts[-1] = ("CAPREV",) + parts[-1][1:]
            elif kind == "bridge":
                if remaining >= 2.0:          # the deck reaches 2 m onto the road
                    lay(last, X, h, psi, total, grade=carry[0])
            elif kind == "junction":
                # The line ends on the other road's centre: end on its surface, either
                # here (short of the centre) or with one more short part (past it),
                # whichever stays further inside that road's edges.
                inside = other_half - 1.0
                short_by, over_by = remaining - inside, (last.fwd - remaining) - inside
                if over_by < short_by:
                    # end at the other road's surface height right where this part ends
                    tip = X + d_of(psi) * last.fwd
                    lay(last, X, h, psi, total, surface(tip[0], tip[1]) if surface else None)
            elif remaining >= 3.0:
                lay(last, X, h, psi, total, grade=carry[0])
            break
        lo, hi = s_cur - 3.0, s_cur + 90.0
        # Through a switchback turn the road may stray further from OSM's apex (tighter
        # than any vanilla curve): it turns on the tightest curves in one piece instead
        # of a fan of joints.
        tol_here = tol if tol_s is None else max(tol, float(np.interp(s_cur, prof_s, tol_s)),
                                                 float(np.interp(min(total, s_cur + 15.0), prof_s, tol_s)))
        dev1, s1, h1, E1, psi1 = eval_from(X[None], np.array([psi]), lo, hi)
        dev1, s1, h1, E1, psi1 = dev1[0], s1[0], h1[0], E1[0], psi1[0]
        ok1 = (s1 - s_cur > 0.3 * fwds) & (s1 <= total + 1.0) & (s1 >= 0)
        idx1 = np.where(ok1)[0]
        if not len(idx1) or dev1[idx1].min() > 2 * tol_here:
            # No part can turn this tight (a switchback): step back onto the line with
            # its own heading, a sharp joint, and lay a short part across the joint.
            X, h, psi, s_cur = reanchor(X, h, psi, s_cur)
            continue
        dev2, s2, h2, _, _ = eval_from(E1[idx1], psi1[idx1], lo, hi)
        ok2 = (s2 - s1[idx1][:, None] > 0.3 * fwds[None, :]) & (s2 <= total + 1.0) & (s2 >= 0)
        devmax = np.maximum(dev1[idx1][:, None], dev2)
        s_bend = (sides[idx1][:, None] * sides[None, :]) < 0
        # how far each part's middle would sit off the height profile (a straight part
        # can't follow a bump, e.g. where it must meet a junction's height): shorter
        # parts win there
        P = lambda s: np.interp(s, prof_s, prof_h)      # noqa: E731
        s1i = s1[idx1]
        verr1 = np.abs((h + P(s1i)) / 2 - P((s_cur + s1i) / 2))
        run = np.maximum(s1i - s_cur, 1.0)
        if carry[0] is not None:
            # just past a sharp joint the part keeps the grade it came in with (a left
            # curve, laid backwards, the steeper for it): the further that takes it off
            # the profile, the worse
            tphi = np.clip(carry[0] / np.where(sides[idx1] < 0, arc_cos[idx1], 1.0), -0.55, 0.55)
            rise = fwds[idx1] * np.sin(np.arctan(tphi))
            verr1 = np.maximum(verr1, np.abs(h + rise - P(s1i)))
            zpen = np.zeros(len(s1i))
        else:
            # a part ending round a sharp joint or a switchback turn should arrive at the
            # grade there, so the short part across the joint lies on both sides: a
            # change of grade belongs at an ordinary joint before it
            kz = zone_k(s1i)
            grade1 = (P(s1i) - h) / run
            zpen = np.where(kz >= 0, 20 * np.maximum(0, np.abs(grade1 - z_slope[np.maximum(kz, 0)]) - 0.03), 0.0)
        verr2 = np.abs((P(s1i)[:, None] + P(s2)) / 2 - P((s1i[:, None] + s2) / 2))
        vcost = 4 * np.maximum(0, verr1 - 0.03)[:, None] + 4 * np.maximum(0, verr2 - 0.03) + zpen[:, None]
        cost2 = (10 * np.maximum(0, devmax - tol_here) + devmax + 0.15 * np.degrees(h2)
                 + 0.05 * np.degrees(h1[idx1])[:, None] - 0.04 * (s2 - s_cur) + 0.3 * s_bend + vcost)
        cost2 = np.where(ok2, cost2, np.inf)
        best = cost2.min(axis=1)
        # a part that brings the line within reach of its end needs no follower
        near_end = total - s1[idx1] < 6.3
        single = (10 * np.maximum(0, dev1[idx1] - tol_here) + dev1[idx1] + 0.2 * np.degrees(h1[idx1])
                  - 0.04 * (total - s_cur) + 4 * np.maximum(0, verr1 - 0.03) + zpen)
        best = np.where(near_end, np.minimum(best, single), best)
        if not np.isfinite(best).any():
            best = 10 * dev1[idx1] + 0.1 * np.degrees(h1[idx1]) - 0.04 * (s1[idx1] - s_cur)
        chosen = int(idx1[int(np.argmin(best))])
        if dev1[chosen] > 2 * tol_here:
            X, h, psi, s_cur = reanchor(X, h, psi, s_cur)
            continue
        sh = shapes[chosen]
        s_target = float(s1[chosen])
        X, h, psi = lay(sh, X, h, psi, s_target, grade=carry[0])
        carry[0] = None
        s_cur = max(s_cur + 0.1, s_target)
    return parts, np.array(cl), covers_cl, anchors


def model_end(name):
    """A part's far end in its own model frame (x across, z along)."""
    tail = name.split("_", 1)[1]
    if " " in tail:
        ang, rad = tail.split(" ")
        a = math.radians({"7": 7.5, "22": 22.5, "0": 0.5}.get(ang, float(ang)))
        R = float(rad)
        return R * (1 - math.cos(a)), R * math.sin(a)
    return 0.0, {"25": 25.0, "12": 12.5, "6": 6.25, "6konec": 6.25}[tail]


def part_plane(part, P):
    """Height of a laid part's surface (a plane, level across) over a point."""
    _, S, hs, psim, th = part[:5]
    return hs + float((np.asarray(P, float) - S) @ d_of(psim)) * math.tan(th)


def fit_covers(parts, cl, covers_cl):
    """Pitch each short part across a sharp joint so its two ends lie on the real parts
    before and after it, and give its centreline samples (what the ground is carved
    to) the same heights, so the ground meets its sides."""
    for k, idxs in covers_cl:
        a = k - 1
        while a >= 0 and parts[a][0].startswith("COVER:"):
            a -= 1
        b = k + 1
        while b < len(parts) and parts[b][0].startswith("COVER:"):
            b += 1
        if a < 0 or b >= len(parts):
            continue
        name, S, hs, psim, th = parts[k]
        xe, ze = model_end(name[6:])
        E = S + r_of(psim) * xe + d_of(psim) * ze * math.cos(th)
        hB, hF = part_plane(parts[a], S), part_plane(parts[b], E)
        th2 = math.asin(max(-0.6, min(0.6, (hF - hB) / ze)))
        parts[k] = (name, S, hB, psim, th2)
        for ci in idxs:
            cl[ci, 2] = part_plane(parts[k], cl[ci, :2])


def reach_junctions(pending, built, centerlines, counts):
    """A road that ends at a junction ends where its OSM line does, but the road it
    joins can lie a little off its own line (rounded corners, switchback turns): where
    a junction end stops short of every other surface, lay one more short part on, if
    that lands its tip on the other road. Returns how many were added."""
    pts = np.vstack([b["cl"][:, :2] for b in built])
    hh = np.concatenate([b["cl"][:, 2] for b in built])
    hw = np.concatenate([np.full(len(b["cl"]), b["half"]) for b in built])
    own = np.concatenate([np.full(len(b["cl"]), b["idx"]) for b in built])
    along = np.concatenate([np.r_[0, np.cumsum(np.hypot(*np.diff(b["cl"][:, :2], axis=0).T))] for b in built])
    tree = cKDTree(pts)
    rows = {}
    for k, row in enumerate(pending):
        rows.setdefault(row[7], []).append(k)
    inserts = []
    for b in built:
        cl, idx = b["cl"], b["idx"]
        if idx not in rows or len(cl) < 3:
            continue
        cs = np.r_[0, np.cumsum(np.hypot(*np.diff(cl[:, :2], axis=0).T))]
        for at_start in (True, False):
            if (b["k0"] if at_start else b["k1"]) != "junction":
                continue
            P, hP = (cl[0, :2], cl[0, 2]) if at_start else (cl[-1, :2], cl[-1, 2])
            s_end = 0.0 if at_start else cs[-1]
            j = int(np.searchsorted(cs, 3.0)) if at_start else int(np.searchsorted(cs, cs[-1] - 3.0)) - 1
            out = P - cl[int(np.clip(j, 0, len(cl) - 1)), :2]
            if np.hypot(*out) < 0.5:
                continue
            out = out / np.hypot(*out)

            def gap(Q):
                """How far Q lies outside the nearest other surface (negative: inside),
                and that surface's sample."""
                d, kk = tree.query(Q, k=64, distance_upper_bound=25.0)
                best = (99.0, -1)
                for dj, kj in zip(d, kk):
                    if not np.isfinite(dj):
                        break
                    if own[kj] == idx and abs(along[kj] - s_end) < 25.0:
                        continue                   # its own end, not its own other stretch
                    best = min(best, (dj - hw[kj], kj))
                return best

            g0, _ = gap(P)
            if g0 <= 0.25 or g0 > 5.5:
                continue
            T = P + out * 6.25
            gT, kT = gap(T)
            if gT > -0.3:                          # it would pass beside it, or poke out beyond
                continue
            th = math.asin(max(-0.5, min(0.5, (hh[kT] - hP) / 6.25)))
            name = b["fam"] + "_6"
            row = (b["group"], name, P.copy(), float(hP), math.atan2(out[0], out[1]), th,
                   b["lift"] - JUNCTION_DROP, idx, "part")
            inserts.append((rows[idx][0] if at_start else rows[idx][-1] + 1, not at_start, row))
            counts[name] = counts.get(name, 0) + 1
            pts_cl = centerlines[b["centerline"]]["points"]
            tip = [round(float(T[0]), 2), round(float(T[1]), 2), round(float(hh[kT]), 2)]
            if at_start:
                pts_cl.insert(0, tip)
            else:
                pts_cl.append(tip)
    # (at one position a road's start goes in first, so the road before keeps its end next to it)
    for pos, _, row in sorted(inserts, key=lambda t: (-t[0], t[1])):
        pending.insert(pos, row)
    return len(inserts)


def settle(pending):
    """After every road is laid: re-pitch the last part of a road that ends on another
    road (or on its own other stretch) so its tip lies on that road's surface (its
    joint end stays where it is). Returns how many were fitted."""
    n = len(pending)
    geo = []
    for group, name, S, hs, psim, th, lift, road, role in pending:
        xe, ze = model_end(name)
        E = S + r_of(psim) * xe + d_of(psim) * ze * math.cos(th)
        geo.append((xe, ze, E, hs + ze * math.sin(th)))

    def plane(k, P):
        _, _, S, hs, psim, th, _, _, _ = pending[k]
        return hs + float((np.asarray(P) - S) @ d_of(psim)) * math.tan(th)

    # junction ends: a part end meeting no other part end, lying on another road
    pts, own = [], []
    for k, (group, name, S, hs, psim, th, lift, road, role) in enumerate(pending):
        pts += [S, geo[k][2]]
        own += [k, k]
    pts = np.array(pts)
    tree = cKDTree(pts)
    d2, _ = tree.query(pts, k=2)
    # every part's centreline, for "which part is under this point"
    samp, sown, shalf = [], [], []
    for k, (group, name, S, hs, psim, th, lift, road, role) in enumerate(pending):
        xe, ze, E, _ = geo[k]
        m = max(2, int(ze) + 1)
        a = 2 * math.atan2(xe, ze)                 # a curve's angle (0 for a straight)
        for t in np.linspace(0, 1, m):
            if a > 1e-6:                           # along the curve itself, not its chord
                R = ze / math.sin(a)
                x, z = R * (1 - math.cos(a * t)), R * math.sin(a * t)
            else:
                x, z = 0.0, ze * t
            samp.append(S + r_of(psim) * x + d_of(psim) * z * math.cos(th))
            sown.append(k)
            shalf.append(FAMILIES[name.split("_")[0]][0] / 2)
    samp, sown, shalf = np.array(samp), np.array(sown), np.array(shalf)
    stree = cKDTree(samp)
    # Only a road's own two ends: its first part's free end and its last part's (a free
    # end in the middle of a road is a sharp joint under a short part, already fitted).
    by_road = {}
    for k, row in enumerate(pending):
        by_road.setdefault(row[7], []).append(k)
    outer = set()
    for ks in by_road.values():
        for k, nb in ((ks[0], ks[1] if len(ks) > 1 else None), (ks[-1], ks[-2] if len(ks) > 1 else None)):
            if nb is None:
                outer.update((2 * k, 2 * k + 1))
                continue
            near = [pts[2 * nb], pts[2 * nb + 1]]
            far = max((2 * k, 2 * k + 1), key=lambda i: min(np.hypot(*(pts[i] - q)) for q in near))
            outer.add(far)
    todo = []
    for i in np.where(d2[:, 1] > 0.01)[0]:
        if i not in outer:
            continue
        k = own[i]
        road, role = pending[k][7], pending[k][8]
        if role != "part":
            continue
        dd, kk = stree.query(pts[i], k=16, distance_upper_bound=15.0)
        for dj, kj in zip(dd, kk):
            # another road, or this road's own other stretch (a loop's tail)
            if np.isfinite(dj) and dj <= shalf[kj] and (pending[sown[kj]][7] != road or abs(sown[kj] - k) >= 4):
                todo.append((k, i % 2 == 1, sown[kj]))
                break
    def tip(k, tip_is_end):
        group, name, S, hs, psim, th, lift, road, role = pending[k]
        xe, ze = model_end(name)
        E = S + r_of(psim) * xe + d_of(psim) * ze * math.cos(th)
        return (E, hs + ze * math.sin(th)) if tip_is_end else (S, hs)

    def set_tip(k, tip_is_end, target):
        group, name, S, hs, psim, th, lift, road, role = pending[k]
        xe, ze = model_end(name)
        E = S + r_of(psim) * xe + d_of(psim) * ze * math.cos(th)
        hE = hs + ze * math.sin(th)
        if tip_is_end:
            th2 = math.asin(max(-0.6, min(0.6, (target - hs) / ze)))
            pending[k] = (group, name, S, hs, psim, th2, lift, road, role)
        else:
            th2 = math.asin(max(-0.6, min(0.6, (hE - target) / ze)))
            S2 = E - (r_of(psim) * xe + d_of(psim) * ze * math.cos(th2))
            pending[k] = (group, name, S2, target, psim, th2, lift, road, role)

    def pivot(k, tip_is_end):
        """(joint height, the fraction of the way to the tip of any point, plane-wise):
        re-pitched about its joint end, the part's surface over Q is
        joint + (tip - joint) * frac(Q)."""
        group, name, S, hs, psim, th, lift, road, role = pending[k]
        xe, ze = model_end(name)
        E = S + r_of(psim) * xe + d_of(psim) * ze * math.cos(th)
        J, j, T = (S, hs, E) if tip_is_end else (E, hs + ze * math.sin(th), S)
        dv = d_of(psim)
        span = float((T - J) @ dv)
        return j, (lambda Q: float((np.asarray(Q) - J) @ dv) / span) if abs(span) > 0.5 else None

    changed = set()
    # Two roads ending on each other (each one's end part lies on the other's, a node
    # only they share): fitting each to the other in turn chases the two tips upward or
    # downward. Solve for both tips at once, each on the other's surface; where that
    # is ill-posed (the parts lie almost one on the other), both go halfway between.
    by_k = {k: (tip_is_end, other) for k, tip_is_end, other in todo}
    paired = set()
    for k, tip_is_end, other in todo:
        if k in paired or other not in by_k or other in paired:
            continue
        o_tip, o_other = by_k[other]
        if pending[o_other][7] != pending[k][7]:
            continue
        paired.update((k, other))
        (TA, hA), (TB, hB) = tip(k, tip_is_end), tip(other, o_tip)
        jA, fA = pivot(k, tip_is_end)
        jB, fB = pivot(other, o_tip)
        tA = tB = (hA + hB) / 2
        if fA is not None and fB is not None:
            uAB, uBA = fA(TB), fB(TA)
            den = 1 - uAB * uBA
            if abs(den) > 0.3:
                c = jA - jB
                x = c * (uBA - 1) / den
                tA, tB = jA + x, jB + x * uAB + c
        if max(abs(tA - hA), abs(tB - hB)) > 1.5:
            tA = tB = (hA + hB) / 2
        if abs(hA - hB) <= 3.0:
            set_tip(k, tip_is_end, tA)
            set_tip(other, o_tip, tB)
            changed.update((k, other))
    for k, tip_is_end, other in todo:
        if k in paired:
            continue
        P, current = tip(k, tip_is_end)
        target = plane(other, P)
        if abs(target - current) < 0.02 or abs(target - current) > 1.5:   # > 1.5 m: over or under, not a junction
            continue
        set_tip(k, tip_is_end, target)
        changed.add(k)
    return len(changed)


def main():
    elev_path, src = sys.argv[1:3]
    nat = np.load(elev_path).astype(np.float64)
    roads_all = json.load(open(os.path.join(src, "roads", "lines.json")))
    water = json.load(open(os.path.join(src, "water", "lines.json")))
    cell = SIZE / nat.shape[0]

    # creek channels (south-origin grid, like nat)
    wimg = Image.new("1", (nat.shape[1], nat.shape[0]), 0)
    dw = ImageDraw.Draw(wimg)
    whalf = {"river": 10.0, "stream": 6.0, "brook": 4.5, "seasonal": 0.0}
    for ln in water:
        if whalf.get(ln["class"], 0) > 0:
            dw.line([(x / cell, z / cell) for x, z in ln["points"]], fill=1,
                    width=max(1, int(round(2 * whalf[ln["class"]] / cell))))
    ground = Ground(nat, np.asarray(wimg))

    roads = [ln for ln in roads_all if ln["family"] != "trail"]
    trails = [ln for ln in roads_all if ln["family"] == "trail"]
    roads = stitch(roads, lambda ln: (ln["family"], ln["group"], ln["bridge"]))
    trails = stitch(trails, lambda ln: ln["bridge"])

    # connectivity, for end caps: an endpoint touching any other road (not trail)
    dense_all = []
    for idx, ln in enumerate(roads):
        dp = densify(ln["points"], 1.0)
        dense_all.append((idx, dp))
    owner = np.concatenate([np.full(len(dp), idx) for idx, dp in dense_all])
    along = np.concatenate([np.arange(len(dp)) for idx, dp in dense_all])      # metres along its road
    allp = np.vstack([dp for _, dp in dense_all])
    road_tree = cKDTree(allp)
    # bridged spans have no road parts (a bridge model carries them): nothing ends on one
    is_bridge = [ln["bridge"] and float(np.hypot(*np.diff(np.asarray(ln["points"]), axis=0).T).sum()) <= 150.0
                 for ln in roads]
    bridge_ends = np.array([p for ln in roads if ln["bridge"] for p in (ln["points"][0], ln["points"][-1])] or
                           [[-1e9, -1e9]])
    btree = cKDTree(bridge_ends)

    def end_kind(idx, p, at_start):
        """("edge"|"bridge"|"junction"|"dead", half width of the road joined). A road
        that ends on its own middle (a loop's tail) ends at a junction with itself."""
        if not (30 < p[0] < SIZE - 30 and 30 < p[1] < SIZE - 30):
            return "edge", 0.0
        if btree.query(p)[0] < JOIN:                   # the bridge's own end node
            return "bridge", 0.0
        n_own = int((owner == idx).sum())
        near = [k for k in road_tree.query_ball_point(p, 3.0)
                if not is_bridge[owner[k]]
                and (owner[k] != idx or abs(along[k] - (0 if at_start else n_own - 1)) > 25)]
        if near:
            k = min(near, key=lambda k: np.hypot(*(allp[k] - p)))
            return "junction", FAMILIES[roads[owner[k]]["family"]][0] / 2
        return "dead", 0.0

    files = {g: open(os.path.join(src, "roads", "tb_%s.txt" % ("trails" if g == "trails" else "roads_" + g)), "w",
                     newline="\n") for g in ("main", "local", "trails")}
    centres = {}
    counts = {}
    centerlines = []
    built_m = {}
    max_dev = []
    lengths = [float(np.hypot(*np.diff(np.asarray(ln["points"]), axis=0).T).sum()) for ln in roads]
    order = sorted(range(len(roads)), key=lambda i: (ORDER.index(roads[i]["family"]), -lengths[i]))
    pending = []          # (group, name, S, hs, psim, th, lift, road, role)
    hairpins = 0
    levelled = 0
    covers_fitted = 0
    self_pinned = 0
    dense_cls = []        # every road's full centreline and half width
    built = []            # every built road: its centreline, end kinds, class
    for n_done, idx in enumerate(order):
        ln = roads[idx]
        if ln["bridge"] and sum(np.hypot(*np.diff(np.asarray(ln["points"]), axis=0).T)) <= 150.0:
            continue
        fam = ln["family"]
        width, sigma, tol, lift = FAMILIES[fam]
        half = width / 2
        poly = smooth_line(densify(ln["points"], STEP), SMOOTH)
        if len(poly) < 3:
            continue
        seg = np.hypot(*np.diff(poly, axis=0).T)
        s_poly = np.r_[0, np.cumsum(seg)]
        if s_poly[-1] < 0.5:              # even a short stub gets a part (by a bridge, a cap)
            continue
        dvec = np.gradient(poly, axis=0)
        tangent = np.arctan2(dvec[:, 0], dvec[:, 1])
        tangent = np.unwrap(tangent)
        k8 = max(1, int(4.0 / STEP))
        tan_s = np.arctan2(gaussian_filter1d(np.sin(tangent), k8), gaussian_filter1d(np.cos(tangent), k8))
        # height profile: ground across the width, smoothed; pinned where a greater road lies
        ps = np.arange(0, s_poly[-1] + 1e-6, 2.0)
        px = np.interp(ps, s_poly, poly[:, 0])
        pz = np.interp(ps, s_poly, poly[:, 1])
        k_ps = np.clip(np.searchsorted(s_poly, ps), 0, len(s_poly) - 1)
        nrm = np.c_[np.cos(tan_s[k_ps]), -np.sin(tan_s[k_ps])]
        acc = np.zeros(len(ps))
        for off in (-half, -half / 2, 0.0, half / 2, half):
            acc += ground.h_many(ground.nat, px + nrm[:, 0] * off, pz + nrm[:, 1] * off)
        raw = acc / 5
        prof = gaussian_filter1d(raw, sigma / 2.0, mode="nearest")
        # Switchback turns are level: where the road turns more than HAIRPIN_TURN degrees
        # within HAIRPIN_SPAN metres, its two legs overlap at the turn, so they must be
        # at one height there; the climb moves onto the legs either side.
        ut = np.unwrap(tangent)[k_ps]
        half_span = int(HAIRPIN_SPAN / 2 / 2.0)
        turn = np.abs(np.r_[ut[half_span:], np.full(half_span, ut[-1])] - np.r_[np.full(half_span, ut[0]), ut[:-half_span]]) \
            if len(ut) > 2 * half_span else np.zeros(len(ut))
        hair = np.degrees(turn) > HAIRPIN_TURN
        tol_s = np.full(len(ps), tol)
        if hair.any():
            grow = int(10.0 / 2.0)
            hair = np.convolve(hair.astype(float), np.ones(2 * grow + 1), mode="same") > 0
            edges = np.flatnonzero(np.diff(np.r_[0, hair.astype(int), 0]))
            for a, b in zip(edges[::2], edges[1::2]):
                prof[a:b] = prof[a:b].mean()
                tol_s[a:b] = tol + HAIRPIN_TOL
            prof = gaussian_filter1d(prof, 3.0, mode="nearest")
            hairpins += len(edges) // 2
        locked = ground.locked_many(px, pz)
        if locked.any():
            pin = ground.cur_many(px, pz)
            resid = np.where(locked, pin - prof, 0.0)
            sg = PIN_SIGMA / 2.0
            wts = gaussian_filter1d(locked.astype(float), sg, mode="constant")
            corr = gaussian_filter1d(resid, sg, mode="constant") / np.maximum(wts, 1e-6)
            fade = np.clip(wts * 6, 0, 1)
            prof = prof + corr * fade
            prof = np.where(locked, pin, prof)
        prof = limit_grade(prof, 2.0, MAX_GRADE[fam], locked)
        # shapes
        shapes = [Shape(fam + suf, "straight", length=L) for L, suf in STRAIGHTS]
        for ang, R, suf in ARCS:
            for side in (1, -1):
                shapes.append(Shape(fam + suf, "arc", angle=ang, radius=R, side=side))
        cap = Shape(fam + KONEC[0], "straight", length=KONEC[1])
        if np.hypot(*(poly[0] - poly[-1])) < 3.0 and s_poly[-1] > 20.0:   # a loop: it ends on its own start
            k0, k1, other_half = "junction", "junction", half
        else:
            k0, _ = end_kind(idx, poly[0], True)
            k1, other_half = end_kind(idx, poly[-1], False)
        k_start = np.searchsorted(s_poly, min(6.0, s_poly[-1]))
        start_psi = math.atan2(*(poly[k_start] - poly[0])) if k_start > 0 else float(tan_s[0])
        if os.environ.get("RB_DEBUG_ROAD") == str(idx):
            import pickle
            pickle.dump({"poly": poly, "s_poly": s_poly, "tan_s": tan_s, "ps": ps, "prof": prof, "tol": tol,
                         "start_psi": start_psi, "end": (k1, other_half), "k0": k0, "fam": fam, "tol_s": tol_s,
                         "raw": raw}, open(os.path.join(os.environ.get("TEMP", "."), "rb_debug.pkl"), "wb"))
        # A sharp joint gets a short straight part laid across it, which lies flush on
        # both sides only where the road keeps one grade through the joint: give the
        # profile one grade round every sharp corner (turning faster than the tightest
        # curve, 60 degrees in 10 m), lay the road, and round any joint that still fell
        # outside, up to three times (switchback turns stay level: their legs overlap).
        k6 = max(1, int(3.0 / 2.0))
        turn6 = np.abs(np.r_[ut[k6:], np.full(k6, ut[-1])] - np.r_[np.full(k6, ut[0]), ut[:-k6]])             if len(ut) > 2 * k6 else np.zeros(len(ut))
        level = (np.degrees(turn6) > SHARP_TURN) & ~locked & ~hair
        ground_at = lambda x, z: float(ground.cur_many([x], [z])[0])      # noqa: E731
        for attempt in range(3):
            used = level
            prof_l, z_slope = zone_profile(prof, level, locked, hair)
            parts, cl, covers_cl, anchors = follow(
                poly, s_poly, tan_s, ps, prof_l, shapes, tol, start_psi,
                end_mode=(k1, other_half), start_cap=(cap if k0 == "dead" else None), cap_shape=cap,
                surface=ground_at, max_grade=MAX_GRADE[fam], tol_s=tol_s, zones=z_slope)
            grown = level.copy()
            for s_a in anchors:
                grown |= (np.abs(ps - s_a) <= LEVEL_REACH) & ~locked & ~hair
            if (grown == level).all():
                break
            level = grown
        levelled += int(used.any())
        # A road ending on itself (a loop's tail, a lollipop) has not carved its own
        # surface yet when it gets there, so it aimed at the bare ground: lay it again
        # with that end pinned to where its own other stretch actually lies.
        if parts and len(cl) > 2:
            loop = k0 == "junction" and np.hypot(*(poly[0] - poly[-1])) < 3.0
            cs = np.r_[0, np.cumsum(np.hypot(*np.diff(cl[:, :2], axis=0).T))]

            def own_height(p, at_start, cl=cl, cs=cs):
                far = (cs > 25.0) if at_start else (cs < cs[-1] - 25.0)
                d = np.where(far, np.hypot(*(cl[:, :2] - p).T), np.inf)
                j = int(np.argmin(d))
                return float(cl[j, 2]) if d[j] < half + 1.0 else None

            pins = []
            if k0 == "junction" and not loop:
                pins.append((0.0, own_height(poly[0], True)))
            if k1 == "junction":
                pins.append((s_poly[-1], own_height(poly[-1], False)))
            pins = [(s_e, H) for s_e, H in pins if H is not None]
            if pins:
                prof2 = prof.copy()
                for s_e, H in pins:
                    k_e = int(np.clip(np.rint(s_e / 2.0), 0, len(ps) - 1))
                    prof2 += (H - prof_l[k_e]) * np.exp(-0.5 * ((ps - s_e) / (PIN_SIGMA / 2)) ** 2) * ~locked
                cl1 = cl.copy()
                end_pinned = any(s_e > 0 for s_e, _ in pins)

                def surf2(x, z, cl1=cl1):
                    # the end's own other stretch where it lies under the tip, else the ground
                    d = np.hypot(cl1[:, 0] - x, cl1[:, 1] - z)
                    cs1 = np.r_[0, np.cumsum(np.hypot(*np.diff(cl1[:, :2], axis=0).T))]
                    d = np.where(cs1 < cs1[-1] - 25.0, d, np.inf)
                    j = int(np.argmin(d))
                    return float(cl1[j, 2]) if d[j] < half + 1.0 else ground_at(x, z)

                prof_l, z_slope = zone_profile(prof2, used, locked, hair)
                parts, cl, covers_cl, anchors = follow(
                    poly, s_poly, tan_s, ps, prof_l, shapes, tol, start_psi,
                    end_mode=(k1, other_half), start_cap=(cap if k0 == "dead" else None), cap_shape=cap,
                    surface=surf2 if end_pinned else ground_at, max_grade=MAX_GRADE[fam], tol_s=tol_s,
                    zones=z_slope)
                self_pinned += len(pins)
        if not parts:
            continue
        fit_covers(parts, cl, covers_cl)
        covers_fitted += len(covers_cl)
        if str(idx) in os.environ.get("RB_DEBUG_ROADS", "").split(","):
            import pickle
            pickle.dump({"poly": poly, "s_poly": s_poly, "ps": ps, "prof": prof, "prof_l": prof_l, "raw": raw,
                         "z_slope": z_slope, "locked": locked, "hair": hair, "level": used,
                         "parts": parts, "cl": cl, "anchors": anchors, "covers_cl": covers_cl,
                         "tan_s": tan_s, "start_psi": start_psi, "k0": k0, "k1": k1, "other_half": other_half,
                         "tol": tol, "tol_s": tol_s, "fam": fam, "half": half},
                        open(os.path.join(os.environ.get("TEMP", "."), "rb_road_%d.pkl" % idx), "wb"))
        # how far the parts stray from the OSM line
        dd, kk = cKDTree(poly).query(cl[:, :2])
        inner = (s_poly[kk] > 8.0) & (s_poly[kk] < s_poly[-1] - 8.0)
        if inner.any():
            worst = int(np.argmax(np.where(inner, dd, -1)))
            max_dev.append((float(dd[inner].max()), ln.get("name") or fam, float(cl[worst, 0]), float(cl[worst, 1])))
        for name, S, hs, psim, th in parts:
            extra, role = 0.0, "part"
            if name.startswith("COVER:"):
                name, extra, role = name[6:], 0.01, "cover"
            if name == "CAPREV" or name.endswith(KONEC[0]):
                role = "cap"
            # on a greater (or earlier) road's surface: just under it
            tip = S + d_of(psim) * 6.0
            if ground.locked_many(np.array([S[0], tip[0]]), np.array([S[1], tip[1]])).any():
                extra -= JUNCTION_DROP
            if name == "CAPREV":
                name = fam + KONEC[0]
                # reverse: the cap laid from X toward the end; its origin must be at the far end
                L = KONEC[1]
                E = S + d_of(psim) * L * math.cos(th)
                hE = hs + L * math.sin(th)
                S, hs, psim, th = E, hE, psim + math.pi, -th
            pending.append((ln["group"], name, S, hs, psim, th, lift + extra, idx, role))
            counts[name] = counts.get(name, 0) + 1
        ground.carve(cl[:, :2], cl[:, 2], half)
        centerlines.append({"family": fam, "group": ln["group"], "name": ln.get("name", ""),
                            "points": [[round(float(x), 2), round(float(z), 2), round(float(hh), 2)]
                                       for x, z, hh in np.vstack([cl[::2], cl[-1:]])]})
        dense_cls.append((cl, half))
        built.append({"idx": idx, "cl": cl, "half": half, "k0": k0, "k1": k1, "fam": fam, "group": ln["group"],
                      "lift": lift, "centerline": len(centerlines) - 1})
        built_m[fam] = built_m.get(fam, 0.0) + float(np.hypot(*np.diff(cl[:, :2], axis=0).T).sum())
        if n_done % 100 == 0:
            print("  %d / %d roads" % (n_done, len(order)), flush=True)

    final = ground.current()
    ends_reached = reach_junctions(pending, built, centerlines, counts)
    if os.environ.get("RB_DUMP_PENDING"):
        import pickle
        pickle.dump(pending, open(os.path.join(os.environ.get("TEMP", "."), "rb_pending.pkl"), "wb"))
    ends_fitted = settle(pending)
    part_rows = {"main": [], "local": []}
    for group, name, S, hs, psim, th, lift, road, role in pending:
        part_rows[group].append({"road": int(road), "role": role, "name": name})
        if name not in centres:
            centres[name] = model_centre(name)
        C = centres[name]
        d, r = d_of(psim), r_of(psim)
        pos = S + r * C[0] + d * (C[2] * math.cos(th) - C[1] * math.sin(th))
        py = hs + C[1] * math.cos(th) + C[2] * math.sin(th)
        rel = py + lift - bilinear(final, pos[0] / cell, pos[1] / cell)
        files[group].write('"%s";%.3f;%.3f;%.3f;%.3f;0.000;1.000;%.3f;\n'
                           % (name, pos[0] + EASTING, pos[1], math.degrees(psim) % 360, -math.degrees(th), rel))

    # Every built road's centreline with its half width: trails, water and stones
    # don't go on road surfaces.
    rc_pts = np.vstack([c[:, :2] for c, _ in dense_cls])
    rc_h = np.concatenate([c[:, 2] for c, _ in dense_cls])
    rc_half = np.concatenate([np.full(len(c), hw) for c, hw in dense_cls])
    rc_tree = cKDTree(rc_pts)

    def on_road(pts, margin, heights=None, below=0.3):
        """Which points lie on a road surface (within margin); with heights, only
        those no more than `below` under that surface (anything deeper is buried
        in the road's fill and can't show)."""
        pts = np.atleast_2d(pts)
        d, k = rc_tree.query(pts, k=6, distance_upper_bound=20.0)
        ok = np.isfinite(d)
        k = np.where(ok, k, 0)
        hit = ok & (d <= rc_half[k] + margin)
        if heights is not None:
            hit &= np.asarray(heights)[:, None] > rc_h[k] - below
        return hit.any(axis=1)

    # Trails: 10 m parts on the ground, pitched and rolled to it.
    trail_skipped = 0
    gz_, gx_ = np.gradient(final, cell)
    slope = np.hypot(gx_, gz_)
    tcen = {nm: model_centre(nm) for nm in (TRAIL, TRAIL_ROCK)}
    trail_n = 0
    trail_m = 0.0
    for ln in trails:
        span = sum(np.hypot(*np.diff(np.asarray(ln["points"]), axis=0).T))
        if ln["bridge"] and span <= 150.0:
            continue
        trail_m += span
        for p, q, length in chain(ln["points"], {TRAIL_LEN: TRAIL}, None):
            p, q = np.asarray(p, float), np.asarray(q, float)
            along = p + np.outer(np.linspace(0, 1, 5), q - p)
            if on_road(along, 0.3).any():           # at or across a road: the road is the surface
                trail_skipped += 1
                continue
            psi = math.atan2(q[0] - p[0], q[1] - p[1])
            hp = bilinear(final, p[0] / cell, p[1] / cell)
            hq = bilinear(final, q[0] / cell, q[1] / cell)
            th = math.asin(max(-0.9, min(0.9, (hq - hp) / length)))
            c = (p + q) / 2
            r = r_of(psi)
            hl = bilinear(final, (c[0] - r[0] * TRAIL_W / 2) / cell, (c[1] - r[1] * TRAIL_W / 2) / cell)
            hr = bilinear(final, (c[0] + r[0] * TRAIL_W / 2) / cell, (c[1] + r[1] * TRAIL_W / 2) / cell)
            roll = math.degrees(math.atan((hr - hl) / TRAIL_W))
            ix = min(slope.shape[1] - 1, max(0, int(c[0] / cell)))
            iz = min(slope.shape[0] - 1, max(0, int(c[1] / cell)))
            name = TRAIL_ROCK if slope[iz, ix] > ROCK_SLOPE else TRAIL
            C = tcen[name]
            d = d_of(psi)
            pos = p + r * C[0] + d * (C[2] * math.cos(th) - C[1] * math.sin(th))
            py = hp + C[1] * math.cos(th) + C[2] * math.sin(th)
            rel = py + TRAIL_LIFT - bilinear(final, pos[0] / cell, pos[1] / cell)
            files["trails"].write('"%s";%.3f;%.3f;%.3f;%.3f;%.3f;1.000;%.3f;\n'
                                  % (name, pos[0] + EASTING, pos[1], math.degrees(psi) % 360, -math.degrees(th),
                                     roll, rel))
            counts[name] = counts.get(name, 0) + 1
            trail_n += 1
    for fh in files.values():
        fh.close()

    # Water: absolute heights from tools/osm_water.py, relative to the carved ground.
    wabs = json.load(open(os.path.join(src, "water", "water_abs.json")))
    water_dropped = {}
    water_shortened = 0
    kept = []

    def water_hits(tpl, x, z, dvec, pitch, scale, absolute):
        L = float(tpl.split("_")[-1]) * scale
        half_w = float(tpl.split("_")[1]) * scale / 2
        f = np.linspace(-L / 2, L / 2, 9)
        pts = np.array([x, z]) + np.outer(f, dvec)
        level = absolute - f * math.sin(math.radians(pitch))    # pitch > 0: the front lower
        return on_road(pts, half_w * 0.6, level).any()

    for row in wabs:
        tpl, x, z, yaw, pitch, roll, scale, absolute = row
        a = math.radians(yaw)
        dvec = np.array([math.sin(a), math.cos(a)])
        if tpl.startswith(("stream_", "river_")):
            hit = water_hits(tpl, x, z, dvec, pitch, scale, absolute)
            if hit:
                # Where a creek meets a road (a culvert), keep water up to the road's
                # edge: the part of the piece away from the road, as shorter pieces.
                base = "_".join(tpl.split("_")[:2])
                L = float(tpl.split("_")[-1]) * scale
                subs = []
                for sub in (12, 6):
                    if sub * scale >= L - 1e-6:
                        continue
                    Ls = sub * scale
                    for off in np.arange(-L / 2 + Ls / 2, L / 2 - Ls / 2 + 1e-6, Ls):
                        c = np.array([x, z]) + dvec * off
                        lev = absolute - off * math.sin(math.radians(pitch))
                        if not water_hits("%s_%d" % (base, sub), c[0], c[1], dvec, pitch, scale, lev):
                            subs.append(["%s_%d" % (base, sub), float(c[0]), float(c[1]), yaw, pitch, roll, scale, lev])
                    if subs:
                        break
                if subs:
                    kept.extend(subs)
                    water_shortened += 1
                    continue
        elif tpl.startswith("pond_"):
            def pond_hits(cx, cz, sc):
                s = 25.0 * sc
                gx, gz = np.meshgrid(np.linspace(-s, s, 9), np.linspace(-s, s, 9))
                return on_road(np.c_[cx + gx.ravel(), cz + gz.ravel()], 0.5, np.full(81, absolute)).any()
            hit = pond_hits(x, z, scale)
            if hit and tpl == "pond_50x50":
                # The square tile reaches past the pond onto a road at the water's level:
                # split it into quarters, then sixteenths, keeping those off the road.
                r_ = math.radians(yaw)
                ax_, az_ = np.array([math.cos(r_), -math.sin(r_)]), np.array([math.sin(r_), math.cos(r_)])
                subs = []
                for n_ in (2, 4):
                    sc = scale / n_
                    step = 50.0 * sc
                    for i_ in range(n_):
                        for j_ in range(n_):
                            c = np.array([x, z]) + ax_ * (i_ - (n_ - 1) / 2) * step + az_ * (j_ - (n_ - 1) / 2) * step
                            if not pond_hits(c[0], c[1], sc):
                                subs.append([tpl, float(c[0]), float(c[1]), yaw, pitch, roll, sc, absolute])
                    if subs:
                        break
                if subs:
                    kept.extend(subs)
                    water_shortened += 1
                    continue
        else:                                        # stones, waterfall rocks
            hit = on_road(np.array([x, z]), 0.5).any()
        if hit:
            water_dropped[tpl.split("_")[0]] = water_dropped.get(tpl.split("_")[0], 0) + 1
        else:
            kept.append(row)
    with open(os.path.join(src, "water", "tb_water.txt"), "w", newline="\n") as fh:
        for tpl, x, z, yaw, pitch, roll, scale, absolute in kept:
            rel = absolute - bilinear(final, x / cell, z / cell)
            fh.write('"%s";%.3f;%.3f;%.3f;%.3f;%.3f;%.3f;%.3f;\n' % (tpl, x + EASTING, z, yaw, pitch, roll, scale, rel))
    # The same with absolute heights, for tools/water_fit.py (the last step).
    json.dump([[tpl, round(float(x), 3), round(float(z), 3), round(float(yaw), 3), round(float(pitch), 3),
                round(float(roll), 3), round(float(scale), 4), round(float(absolute), 3)]
               for tpl, x, z, yaw, pitch, roll, scale, absolute in kept],
              open(os.path.join(src, "water", "water_roads_abs.json"), "w"))

    np.save(os.path.join(src, "roads", "elevation.npy"), final.astype(np.float32))
    json.dump(centerlines, open(os.path.join(src, "roads", "centerlines.json"), "w"))
    json.dump(part_rows, open(os.path.join(src, "roads", "parts.json"), "w"))
    change = final - nat
    moved = np.abs(change) > 0.02
    with open(os.path.join(src, "roads", "build_summary.txt"), "w", newline="\n") as fh:
        fh.write("Roads built from straight and curve parts (tools/road_build.py)\n\n")
        fh.write("roads: %d lines after joining continuing ways; trails: %d\n" % (len(roads), len(trails)))
        for fam in ORDER:
            fh.write("  %-5s %7.1f km\n" % (fam, built_m.get(fam, 0) / 1000))
        fh.write("  trails %6.1f km, %d parts (%d left out where a trail crosses a road)\n"
                 % (trail_m / 1000, trail_n, trail_skipped))
        fh.write("level switchback turns: %d; roads given one grade round sharp corners: %d; road ends pinned "
                 "to the same road's own other stretch: %d\n" % (hairpins, levelled, self_pinned))
        fh.write("short parts across sharp joints fitted to the parts either side: %d; road ends fitted to the road "
                 "they end on: %d (%d of them carried one part on to reach it)\n"
                 % (covers_fitted, ends_fitted, ends_reached))
        fh.write("water objects left out where they reached a road (culverts): %s\n"
                 % ", ".join("%s %d" % kv for kv in sorted(water_dropped.items())))
        fh.write("water parts cut short to stop at a road's edge: %d\n" % water_shortened)
        if max_dev:
            md = np.array([m[0] for m in max_dev])
            w = max(max_dev)
            fh.write("\nlargest distance of a road's parts from its (rounded) OSM line, ends aside: median %.2f m, 95%% %.2f m, max %.1f m\n"
                     % (np.median(md), np.percentile(md, 95), md.max()))
            fh.write("  (the most: %s at %.0f, %.0f)\n" % (w[1], w[2], w[3]))
        fh.write("\nparts:\n")
        for nm in sorted(counts):
            fh.write("  %-16s %6d\n" % (nm, counts[nm]))
        fh.write("  %-16s %6d\n" % ("total", sum(counts.values())))
        fh.write("\nground carved under roads: %d height points changed; cut up to %.1f m, fill up to %.1f m, median %.2f m\n"
                 % (int(moved.sum()), -change.min(), change.max(), float(np.median(np.abs(change[moved]))) if moved.any() else 0))
    print(open(os.path.join(src, "roads", "build_summary.txt")).read())


if __name__ == "__main__":
    main()
