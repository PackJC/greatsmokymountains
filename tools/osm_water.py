"""Turn OpenStreetMap rivers, creeks, ponds and waterfalls into DayZ water that the
ground holds.

    python tools/osm_water.py source/water/osm_water.json <heights wrp> tools/georef.json source/water

Writes into <out>:
  tb_water.txt         stream and river parts along every perennial creek and river,
                       pond tiles over ponds, rocks and pools at the waterfalls
                       (Terrain Builder object import, height relative to the ground)
  elevation.npy        the heightmap with a channel under every creek, pond basins and
                       pools, and banks round them (4096 x 4096 float32, row 0 = south)
  lines.json           every waterway in map coordinates as laid (fitted to the valley
                       floor), with its class, for tools/paint_roads.py, the forest and rocks
  water_abs.json       the water objects with absolute heights, for tools/road_build.py
  channels.json        each channel's line, water surface and shape, for tools/water_fit.py
  summary.txt          what went where

Where the water goes. OSM's creek lines lie up to 40 m off this terrain's own
valley floors (the old heightmap and the real world differ by about that), so a
creek drawn on OSM's line would sit on a hillside. Each line is moved to the
lowest ground within FIT_REACH of it, smoothly (dynamic programming over sideways
offsets, a little cost for each metre off OSM's line and for bending), with two
pins: a creek passes under the middle of any road or trail bridge OSM has over it,
and a creek that ends on another ends exactly on the other's fitted line. Then:
  river                          river_24_*  (24 m pieces, scaled to suit)
  named perennial stream         stream_14_* (14 m wide pieces, scaled)
  unnamed perennial stream       stream_14_*, a narrower channel
  seasonal stream, ditch         no water; streambed paint only
Culverts (tunnel=culvert) are left dry. The water surface follows the lowest
ground along the creek, never rising downstream, WATER_BELOW under it; a
tributary meets its creek at the creek's level.

How the ground holds it (tools/water_fit.py). The water models are flat sheets.
The 5 m grid points within `core` of the line become the bed, `bed` under the
water; out to the sheet's edge they are raised, if lower, to `bank` over it. The
waterline then falls at most EDGE_DIAG * bed / (bed + bank) past the core, so each
class's sheets are scaled to reach that far and 0.4 m more, and every sheet edge
is then checked against the ground and the bank points under it raised until it's
buried. Ponds and waterfall pools are done the same way round their shores.
"""

import json
import math
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import bilinear, load_heights  # noqa: E402
from geo import utm  # noqa: E402
from osm_roads import deviation, inside_runs, next_at_distance  # noqa: E402
from road_build import stitch  # noqa: E402
from water_fit import (EDGE_DIAG, EDGE_REACH, apply_targets, channel_targets, distance_to_polygon,  # noqa: E402
                       inside_polygon, sheet_transforms, solve_ground)

EASTING = 200000.0
SPACING = 2.5                    # metres between samples along a waterway
# class -> pieces {length: template}, piece half-width in the model, channel core
# half-width, bed depth under the water, bank height over it, bend tolerance
CLASSES = {
    "river": ({24.0: "river_24_24", 12.0: "river_24_12", 6.0: "river_24_6"}, 12.0, 7.0, 0.9, 0.8, 0.6),
    "stream": ({24.0: "stream_14_24", 12.0: "stream_14_12", 6.0: "stream_14_6"}, 7.0, 3.5, 0.5, 0.5, 0.5),
    "brook": ({24.0: "stream_14_24", 12.0: "stream_14_12", 6.0: "stream_14_6"}, 7.0, 3.0, 0.4, 0.5, 0.4),
}
CLASS_ORDER = ["river", "stream", "brook", "seasonal"]
EDGE_MARGIN = 0.4                # sheets reach this far past the farthest waterline
WATER_BELOW = 0.15               # water surface under the lowest ground along the creek
MAX_CUT = 2.5                    # the water never sits more than this under the ground
OVERLAP = 0.6                    # consecutive pieces overlap this much, closing small bends
COVER_TURN = 2.0                 # joints turning more than this get a short part across the bend
FIT_REACH = 40                   # how far (m) a creek may move off OSM's line
FIT_STEP = 5.0                   # metres between fitting stations
FIT_SLEW = 2                     # at most this many metres sideways per station
FIT_OFF_COST = 0.01              # per metre off OSM's line (in metres of height)
FIT_BEND_COST = 0.05             # per (metre sideways per station) squared
JUNCTION = 6.0                   # a line end this near another line's OSM line ends on it
CONTACT = {"river": 10.0, "stream": 6.0, "brook": 6.0}   # a creek this near one already laid joins it there
MIN_RUN = 4                      # stretches shorter than this many fitting stations are dropped
TRIB_BLEND = 30.0                # a tributary's last metres slope to its creek's level
POND_TILE, POND_SCALE = "pond_50x50", 0.25           # 13 m tiles follow the shore closely
POND_DEPTH, POND_BANK, POND_SHORE = 1.2, 1.2, 3.0
POND_REACH = 30.0                # how far a pond may move onto the terrain's own hollow
POOL, POOL_SCALE, POOL_RADIUS, POOL_DEPTH, POOL_BANK = "pond_small_01", 0.3, 3.5, 1.0, 1.0
FALL_HEIGHT = {"Rainbow Falls": 24, "Grotto Falls": 8, "Cataract Falls": 12, "Baskins Creek Falls": 12,
               "Thousand Drips": 24, "Sweat Heifer Cascades": 10, "Trickling Falls": 8}
STONES = ["stones_moss_group_1", "stones_moss_group_2", "stones_moss_group_3"]
STONE_LIFT = {"stones_moss_group_1": 0.01, "stones_moss_group_2": -0.05, "stones_moss_group_3": -0.35}  # model centre
STONE_EVERY = (18.0, 40.0)
# Which way the stream models' water runs isn't known from the files: pieces point
# downstream. If the water flows uphill in game, set this to True and rebuild.
FLOW_REVERSED = False


def sheet_scale(cls):
    """Sheets reach EDGE_REACH past the channel: their edges lie over the banks, whose
    grid points tools/water_fit.py raises until the edges are buried."""
    _, hw, core, _, _, _ = CLASSES[cls]
    return (core + EDGE_REACH) / hw


def waterway_class(tags):
    w = tags.get("waterway")
    if tags.get("tunnel") in ("culvert", "yes"):
        return None
    if w == "river":
        return "river"
    if w == "stream":
        if tags.get("intermittent") == "yes":
            return "seasonal"
        return "stream" if tags.get("name") else "brook"
    if w in ("ditch", "drain", "canal"):
        return "seasonal"
    return None


def densify(points, step):
    pts = np.asarray(points, float)
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.ceil(math.hypot(*(b - a)) / step)))
        for k in range(1, n + 1):
            out.append(a + (b - a) * k / n)
    return np.array(out)


def resample(points, step):
    p = np.asarray(points, float)
    arc = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])
    s = np.arange(0, arc[-1] + 1e-9, step)
    if arc[-1] - s[-1] > 0.5:
        s = np.append(s, arc[-1])
    return np.c_[np.interp(s, arc, p[:, 0]), np.interp(s, arc, p[:, 1])]


def smooth(p, passes):
    q = p.copy()
    for _ in range(passes):
        q[1:-1] = (q[:-2] + 2 * q[1:-1] + q[2:]) / 4
    return q


def ground_min(elev, cell, p):
    """Lowest ground near a point: the four grid nodes around it and the point itself."""
    i, j = int(p[0] / cell), int(p[1] / cell)
    i, j = min(max(i, 0), elev.shape[1] - 2), min(max(j, 0), elev.shape[0] - 2)
    return min(float(elev[j:j + 2, i:i + 2].min()), bilinear(elev, p[0] / cell, p[1] / cell))


def grid_heights(elev, cell, x, z):
    n = elev.shape[0]
    u, v = np.clip(x / cell, 0, n - 1.0001), np.clip(z / cell, 0, n - 1.0001)
    j, i = u.astype(int), v.astype(int)
    fx, fz = u - j, v - i
    return (elev[i, j] * (1 - fx) * (1 - fz) + elev[i, j + 1] * fx * (1 - fz)
            + elev[i + 1, j] * (1 - fx) * fz + elev[i + 1, j + 1] * fx * fz)


def segment_cross(a, b, c, d):
    """Where segment ab crosses segment cd, or None."""
    r, s = b - a, d - c
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    return a + t * r if 0 <= t <= 1 and 0 <= u <= 1 else None


def fit_line(nat, cell, size, points, pins):
    """Move a line to the lowest ground within FIT_REACH of it. pins: [(point, target
    point)]: the station nearest `point` must pass through `target`. Returns the
    stations' base points, normals and the fitted points."""
    base = smooth(resample(points, FIT_STEP), 3)
    t = np.gradient(base, axis=0) if len(base) > 1 else np.array([[1.0, 0.0]])
    t /= np.hypot(t[:, 0], t[:, 1])[:, None] + 1e-12
    nrm = np.c_[-t[:, 1], t[:, 0]]
    offs = np.arange(-FIT_REACH, FIT_REACH + 1, 1.0)
    X = base[:, 0:1] + offs[None, :] * nrm[:, 0:1]
    Z = base[:, 1:2] + offs[None, :] * nrm[:, 1:2]
    cost = grid_heights(nat, cell, X, Z) + FIT_OFF_COST * np.abs(offs)[None, :]
    cost[(X < 1) | (X > size - 1) | (Z < 1) | (Z > size - 1)] += 1e6
    fixed = {}
    for p, target in pins:
        s = int(np.argmin(np.hypot(base[:, 0] - p[0], base[:, 1] - p[1])))
        o = float((target - base[s]) @ nrm[s])
        if abs(o) <= FIT_REACH:
            cost[s, np.abs(offs - o) > 1.5] += 1e6
            fixed[s] = target
    S, K = cost.shape
    D = cost[0].copy()
    back = np.zeros((S, K), np.int8)
    for s in range(1, S):
        best = np.full(K, np.inf)
        arg = np.zeros(K, np.int8)
        for d in range(-FIT_SLEW, FIT_SLEW + 1):
            prev = np.full(K, np.inf)
            if d > 0:
                prev[d:] = D[:K - d]
            elif d < 0:
                prev[:K + d] = D[-d:]
            else:
                prev = D
            cand = prev + FIT_BEND_COST * d * d
            m = cand < best
            best[m] = cand[m]
            arg[m] = d
        D = best + cost[s]
        back[s] = arg
    k = int(np.argmin(D))
    path = np.empty(S, int)
    for s in range(S - 1, -1, -1):
        path[s] = k
        k -= back[s, k]
    fitted = base + offs[path][:, None] * nrm
    fitted = smooth(fitted, 1)
    for s, target in fixed.items():
        fitted[s] = target
    return fitted, abs(offs[path])


class Laid:
    """Points of the creeks laid so far, bucketed by 10 m square, with each one's class."""

    def __init__(self, cell=10.0):
        self.cell, self.d = cell, {}

    def add(self, pts, cls):
        for p in pts:
            self.d.setdefault((int(p[0] // self.cell), int(p[1] // self.cell)), []).append((p[0], p[1], cls))

    def query(self, pts):
        """Distance from each point to the nearest laid point (less a river's extra width),
        and that point."""
        dist = np.full(len(pts), np.inf)
        nearest = np.array(pts, float)
        for k, p in enumerate(pts):
            ci, cj = int(p[0] // self.cell), int(p[1] // self.cell)
            for a in (ci - 1, ci, ci + 1):
                for b in (cj - 1, cj, cj + 1):
                    for x, z, cls in self.d.get((a, b), ()):
                        d = math.hypot(x - p[0], z - p[1]) - (CONTACT["river"] - CONTACT["stream"] if cls == "river" else 0)
                        if d < dist[k]:
                            dist[k], nearest[k] = d, (x, z)
        return dist, nearest


def fit_pond(nat, cell, poly):
    """Move a pond's outline (up to POND_REACH) to where this terrain has a hollow for it:
    a level shore, and nothing inside higher than the shore. Returns the outline and how
    far it moved."""
    from water_fit import inside_polygon as _inside
    shore = densify(poly, SPACING)
    lo, hi = poly.min(0), poly.max(0)
    gx, gz = np.meshgrid(np.arange(lo[0], hi[0] + 1e-6, 5.0), np.arange(lo[1], hi[1] + 1e-6, 5.0))
    gx, gz = gx.ravel(), gz.ravel()
    inside = np.c_[gx, gz][_inside(gx, gz, poly)]
    if not len(inside):
        inside = poly.mean(0)[None, :]
    best = None
    for dx in np.arange(-POND_REACH, POND_REACH + 1e-6, 2.5):
        for dz in np.arange(-POND_REACH, POND_REACH + 1e-6, 2.5):
            s = grid_heights(nat, cell, shore[:, 0] + dx, shore[:, 1] + dz)
            g = grid_heights(nat, cell, inside[:, 0] + dx, inside[:, 1] + dz)
            level = np.percentile(s, 25)
            cost = float(np.std(s) + np.mean(np.clip(g - level, 0, None)) + 0.005 * math.hypot(dx, dz))
            if best is None or cost < best[0]:
                best = (cost, dx, dz)
    _, dx, dz = best
    return poly + np.array([dx, dz]), math.hypot(dx, dz)


def chain_pitched(line, pieces, tol, level_at):
    """Chain straight pieces end to end along a polyline, like tools/osm_roads.py's chain,
    but each piece is pitched to the water's fall along it, so it covers less ground than
    its length: space them by that, so the pitched pieces still meet end to end (on a 20
    degree creek a 24 m piece falls 1.4 m short of a flat 24 m). Returns [(start, end, length)]."""
    pts = np.asarray(line, float)
    lengths = sorted(pieces, reverse=True)
    out, p, seg, t = [], pts[0], 0, 0.0

    def reach(p, seg, t, length):
        d, nxt = length, None
        for _ in range(5):
            nxt = next_at_distance(pts, p, seg, t, d)
            if nxt is None:
                return None
            fall = level_at(p) - level_at(nxt[0])
            d_new = math.sqrt(max(length * length - fall * fall, (0.3 * length) ** 2)) - OVERLAP
            if abs(d_new - d) < 0.005:
                break
            d = d_new
        return nxt
    while True:
        placed = None
        for k, length in enumerate(lengths):
            nxt = reach(p, seg, t, length)
            if nxt is None:
                continue
            q, qseg, qt = nxt
            if tol is None or k == len(lengths) - 1 or deviation(pts, p, seg, q, qseg) <= tol:
                placed = (q, qseg, qt, length)
                break
        if placed is None:
            break
        q, seg, t, length = placed
        out.append((p, q, length))
        p = q
    # Cover the leftover tail with the shortest piece, ending exactly at the line's end.
    end = pts[-1]
    rest = math.hypot(*(end - p))
    shortest = lengths[-1]
    if rest > 0.15 * shortest:
        direction = (end - p) / rest
        fall = level_at(end - direction * shortest) - level_at(end)
        d = math.sqrt(max(shortest * shortest - fall * fall, (0.3 * shortest) ** 2))
        out.append((end - direction * d, end, shortest))
    return out


def main():
    osm_path, heights_path, georef_path, out = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    rng = random.Random(2812533524)
    geo = json.load(open(georef_path))
    ox, oy = geo["offset_x"], geo["offset_y"]
    elev0, terrain, land, land_cell = load_heights(heights_path)
    cell = land[0] * land_cell / terrain[0]
    nat = np.array(elev0, np.float64)
    size = land[0] * land_cell

    def to_map(node):
        x, y = utm(node["lat"], node["lon"], 17)
        return x + ox, y + oy

    elements = json.load(open(osm_path, encoding="utf-8"))["elements"]
    lines, ponds, falls = [], [], []
    for e in elements:
        t = e.get("tags", {})
        if e["type"] == "node":
            if t.get("waterway") == "waterfall":
                x, y = to_map(e)
                if 0 <= x <= size and 0 <= y <= size:
                    falls.append((t.get("name", "waterfall"), x, y))
            continue
        geom = e.get("geometry") or [p for m in e.get("members", []) for p in (m.get("geometry") or [])]
        pts = [to_map(p) for p in geom if p]
        if "waterway" in t:
            cls = waterway_class(t)
            if cls is None:
                continue
            for run in inside_runs(pts):
                lines.append({"points": run, "class": cls, "name": t.get("name", ""), "id": e["id"]})
        elif t.get("natural") == "water" and t.get("water", "pond") in ("pond", "lake", "reservoir", "basin"):
            if len(pts) >= 4 and all(0 <= x <= size and 0 <= y <= size for x, y in pts):
                ponds.append({"points": pts, "name": t.get("name", ""), "id": e["id"]})

    # Ways that simply continue one another (same class and name) become one line.
    n_ways = len(lines)
    lines = stitch(lines, lambda ln: (ln["class"], ln["name"]))

    # Road and trail bridges: a creek passes under the middle of any OSM has over it.
    bridges = []
    roads_lines = os.path.join(os.path.dirname(os.path.abspath(out)), "roads", "lines.json")
    if os.path.exists(roads_lines):
        for rd in json.load(open(roads_lines)):
            if rd.get("bridge"):
                bridges.append(np.asarray(rd["points"], float))

    # Fit the lines to the valley floors: rivers first, then streams, brooks, seasonal;
    # longest first, so a tributary's end can be pinned to the creek it joins.
    def length(ln):
        p = np.asarray(ln["points"], float)
        return float(np.hypot(*np.diff(p, axis=0).T).sum())
    lines.sort(key=lambda ln: (CLASS_ORDER.index(ln["class"]), -length(ln)))
    fitted_lines = []                # (osm points, fitted points) of lines done so far
    fitted, laid = [], Laid()        # the lines as laid; their points, to find creeks already there
    moved, pinned_bridges, pinned_ends, joined, dropped = [], 0, 0, 0, 0
    for ln in lines:
        osm = np.asarray(ln["points"], float)
        pins = []
        lo, hi = osm.min(0), osm.max(0)
        for b in bridges:
            if (b.min(0) > hi).any() or (b.max(0) < lo).any():
                continue
            for a1, a2 in zip(osm[:-1], osm[1:]):
                for c1, c2 in zip(b[:-1], b[1:]):
                    x = segment_cross(a1, a2, c1, c2)
                    if x is not None:                  # the creek passes under the bridge there
                        pins.append((x, x))
                        pinned_bridges += 1
        for end in (osm[0], osm[-1]):
            best = None
            for o_lo, o_hi, o_osm, o_fit in fitted_lines:
                if (end < o_lo - JUNCTION).any() or (end > o_hi + JUNCTION).any():
                    continue
                d = np.hypot(o_osm[:, 0] - end[0], o_osm[:, 1] - end[1])
                k = int(np.argmin(d))
                if d[k] <= JUNCTION and (best is None or d[k] < best[0]):
                    fk = int(np.argmin(np.hypot(o_fit[:, 0] - o_osm[k, 0], o_fit[:, 1] - o_osm[k, 1])))
                    best = (d[k], o_fit[fk])
            if best is not None:
                pins.append((end, best[1]))
                pinned_ends += 1
        fit, offs = fit_line(nat, cell, size, osm, pins)
        moved.append(offs)
        # Fitted into a valley a creek already runs down, a line would lay a second set of
        # water beside the first. Downhill first; then keep only the stretches that aren't
        # on a creek already laid, each ending on that creek where it meets it.
        if ground_min(nat, cell, fit[0]) < ground_min(nat, cell, fit[-1]):
            fit = fit[::-1]
        near, nearest = laid.query(fit)
        contact = near <= CONTACT[ln["class"]] if ln["class"] in CONTACT else np.zeros(len(fit), bool)
        k = 0
        while k < len(fit):
            if contact[k]:
                k += 1
                continue
            e = k
            while e < len(fit) and not contact[e]:
                e += 1
            run = list(fit[k:e])
            if e < len(fit):                      # meets a creek already laid: end on it
                run.append(nearest[e])
                joined += 1
            if e - k >= MIN_RUN:
                part = dict(ln)
                part["points"] = [list(map(float, p)) for p in run]
                fitted.append(part)
                laid.add(np.asarray(run), ln["class"])
            k = e
        if contact.all():
            dropped += 1
        ro = resample(osm, FIT_STEP)
        fitted_lines.append((ro.min(0), ro.max(0), ro, fit))
    moved = np.concatenate(moved) if moved else np.zeros(1)
    lines = fitted

    objects = []                     # (template, x, z, yaw, pitch, scale, absolute height)
    channels = []                    # for tools/water_fit.py
    metres, pieces_n = {}, {}
    covers = 0
    wet = []                         # (samples, levels, class) of every waterway with water
    level_index = []                 # (dense points, levels) to find a creek's level at a junction
    for ln in lines:
        metres[ln["class"]] = metres.get(ln["class"], 0.0) + length(ln)
        if ln["class"] not in CLASSES:
            continue
        pieces, hw, core, bed, bank, tol = CLASSES[ln["class"]]
        scale = sheet_scale(ln["class"])
        dense = densify(ln["points"], SPACING)
        ground = np.array([ground_min(nat, cell, p) for p in dense])
        if ground[0] < ground[-1]:            # make it run downhill
            dense, ground = dense[::-1], ground[::-1]
            ln["points"] = ln["points"][::-1]
        # Never rising downstream, except where that would sink it more than MAX_CUT
        # under the ground (a road fill, or a hump the fit couldn't get round).
        levels = np.empty_like(ground)
        run = ground[0]
        for k, g in enumerate(ground):
            run = max(min(run, g), g - MAX_CUT)
            levels[k] = run - WATER_BELOW
        # A tributary meets its creek just under the creek's water: its last metres slope
        # down to the creek's level there, less the creek's fall across the tributary's
        # sheets, so they stay under the creek's water where they overlap it.
        end = dense[-1]
        for o_lo, o_hi, pts_o, lev_o in level_index:
            if (end < o_lo - 3).any() or (end > o_hi + 3).any():
                continue
            d = np.hypot(pts_o[:, 0] - end[0], pts_o[:, 1] - end[1])
            k = int(np.argmin(d))
            if d[k] <= 3.0:
                k0, k1 = max(0, k - 5), min(len(lev_o) - 1, k + 5)
                grade = abs(lev_o[k0] - lev_o[k1]) / max(float(np.hypot(*(pts_o[k1] - pts_o[k0]))), 1.0)
                target = lev_o[k] - 0.06 - grade * hw * scale
                if levels[-1] > target:
                    arc_back = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(dense[::-1], axis=0).T))])[::-1]
                    levels -= (levels[-1] - target) * np.clip(1 - arc_back / TRIB_BLEND, 0, 1)
                    levels = np.minimum.accumulate(levels)
                break
        level_index.append((dense.min(0), dense.max(0), dense, levels))

        def level_at(q):
            k = int(np.argmin(np.hypot(dense[:, 0] - q[0], dense[:, 1] - q[1])))
            return float(levels[k])
        scaled = {length_ * scale: name for length_, name in pieces.items()}
        shortest = min(scaled)
        placed = []
        for k, (p, q, plen) in enumerate(chain_pitched(ln["points"], scaled, tol, level_at)):
            if FLOW_REVERSED:
                p, q = q, p
            hp, hq = level_at(p), level_at(q)
            c = (p + q) / 2
            yaw = math.degrees(math.atan2(q[0] - p[0], q[1] - p[1])) % 360
            pitch = math.degrees(math.asin(max(-1.0, min(1.0, (hp - hq) / plen))))
            objects.append((scaled[plen], c[0], c[1], yaw, pitch, scale, (hp + hq) / 2))
            pieces_n[scaled[plen]] = pieces_n.get(scaled[plen], 0) + 1
            placed.append((np.asarray(p), np.asarray(q), yaw, pitch, hp, hq))
        # A bend between two straight parts opens a wedge on its outer bank; cover each
        # joint with the shortest part along the bisector.
        for (p0, q0, y0, pt0, hp0, hq0), (p1, q1, y1, pt1, hp1, hq1) in zip(placed, placed[1:]):
            turn = (y1 - y0 + 180) % 360 - 180
            if abs(turn) > COVER_TURN:
                j = q1 if FLOW_REVERSED else q0
                # Low enough to lie under both pieces wherever it overlaps them: they slope
                # differently from it along it, and across it at the bend's angle.
                pc = (pt0 + pt1) / 2
                s0, s1, sc_ = (math.sin(math.radians(v)) for v in (pt0, pt1, pc))
                half = shortest / 2
                sink = 0.06 + max(0.0, half * (sc_ - s0), half * (s1 - sc_)) +                     hw * scale * math.sin(math.radians(abs(turn) / 2)) * max(abs(s0), abs(s1))
                objects.append((scaled[shortest], j[0], j[1], (y0 + turn / 2) % 360, pc, scale,
                                (hq0 if not FLOW_REVERSED else hq1) - sink))
                covers += 1
        # The water surface the sheets make, along the line: each dense point on its piece.
        surf = levels.copy()
        if placed:
            P = np.array([pl[0] for pl in placed])
            Q = np.array([pl[1] for pl in placed])
            HP = np.array([pl[4] for pl in placed])
            HQ = np.array([pl[5] for pl in placed])
            dv = Q - P
            dl2 = np.maximum((dv ** 2).sum(1), 1e-9)
            for s0 in range(0, len(dense), 2000):
                pts = dense[s0:s0 + 2000]
                tt = np.clip(((pts[:, None, :] - P[None]) * dv[None]).sum(2) / dl2[None], 0, 1)
                proj = P[None] + tt[..., None] * dv[None]
                dd = np.hypot(*(pts[:, None, :] - proj).transpose(2, 0, 1))
                k = np.argmin(dd, axis=1)
                ti = tt[np.arange(len(pts)), k]
                surf[s0:s0 + 2000] = HP[k] + (HQ[k] - HP[k]) * ti
        channels.append({"kind": "line", "class": ln["class"], "points": dense.round(3).tolist(),
                         "surface": surf.round(3).tolist(), "core": core, "bed": bed, "bank": bank,
                         "half": hw * scale})
        wet.append((dense, surf, ln["class"]))

    # Ponds: small tiles over the pond and just past its shore, a basin under them and
    # banks round it.
    pond_report = []
    pond_moves = []
    for pd in ponds:
        poly, moved_by = fit_pond(nat, cell, np.asarray(pd["points"], float))
        pond_moves.append(moved_by)
        shore = densify(poly, SPACING)
        # Lower quarter of the shore, not its lowest point: on a dammed or hillside pond
        # the lowest shore point is the foot of the dam.
        level = float(np.percentile([ground_min(nat, cell, p) for p in shore], 25)) - WATER_BELOW
        tile = 50.0 * POND_SCALE
        waterline = POND_SHORE + EDGE_DIAG * POND_DEPTH / (POND_DEPTH + POND_BANK)
        tiles = 0
        xs = np.arange(poly[:, 0].min() - waterline - tile / 2, poly[:, 0].max() + waterline + tile, tile)
        zs = np.arange(poly[:, 1].min() - waterline - tile / 2, poly[:, 1].max() + waterline + tile, tile)
        for x in xs:
            for z in zs:
                sx, sz = np.meshgrid(np.linspace(x - tile / 2, x + tile / 2, 5), np.linspace(z - tile / 2, z + tile / 2, 5))
                sx, sz = sx.ravel(), sz.ravel()
                inside = inside_polygon(sx, sz, poly)
                if inside.any() or (distance_to_polygon(sx, sz, poly) <= waterline + 0.5).any():
                    objects.append((POND_TILE, x, z, 0.0, 0.0, POND_SCALE, level))
                    tiles += 1
        channels.append({"kind": "pond", "polygon": poly.round(3).tolist(), "level": level, "depth": POND_DEPTH,
                         "bank": POND_BANK, "shore": POND_SHORE,
                         "reach": waterline + 0.5 + tile * math.sqrt(2) + EDGE_DIAG})
        pond_report.append((pd["name"] or "pond %d" % pd["id"], tiles, level))
        pieces_n[POND_TILE] = pieces_n.get(POND_TILE, 0) + tiles

    # Stones along the creeks, on the bed.
    stones = 0
    for dense, surf, cls in wet:
        core, bed = CLASSES[cls][2], CLASSES[cls][3]
        arc = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(dense, axis=0).T))])
        s = rng.uniform(*STONE_EVERY)
        while s < arc[-1]:
            k = int(np.searchsorted(arc, s))
            k = min(k, len(dense) - 2)
            d = dense[k + 1] - dense[k]
            nrm = np.array([-d[1], d[0]]) / (np.hypot(*d) or 1)
            p = dense[k] + nrm * rng.uniform(-core * 0.6, core * 0.6)
            name, sc = rng.choice(STONES), rng.uniform(0.7, 1.3)
            objects.append((name, p[0], p[1], rng.uniform(0, 360), 0.0, sc,
                            float(surf[k]) - bed + STONE_LIFT[name] * sc - 0.1))
            stones += 1
            s += rng.uniform(*STONE_EVERY)
    pieces_n["streambed stones"] = stones

    # Waterfalls: boulders either side of the creek and a pool at the foot.
    fall_report = []
    for name, x, y in falls:
        best = None
        for dense, surf, cls in wet:
            dd = np.hypot(dense[:, 0] - x, dense[:, 1] - y)
            k = int(dd.argmin())
            if best is None or dd[k] < best[0]:
                best = (dd[k], dense, surf, k, cls)
        if best is None or best[0] > 80:
            fall_report.append((name, "no creek within 80 m; skipped"))
            continue
        _, dense, surf, k, cls = best
        k = min(max(k, 1), len(dense) - 2)
        d = dense[k + 1] - dense[k - 1]
        d = d / (np.hypot(*d) or 1)
        nrm = np.array([-d[1], d[0]])
        height = FALL_HEIGHT.get(name, 6)
        rs = min(2.5, max(0.6, height / 8.0))
        half = CLASSES[cls][1] * sheet_scale(cls)
        top = float(surf[k])
        yaw = math.degrees(math.atan2(d[0], d[1])) % 360
        for side in (-1, 1):
            p = dense[k] + nrm * side * (half + 4 * rs)
            objects.append((rng.choice(["rock_apart1", "rock_apart2"]), p[0], p[1], (yaw + rng.uniform(-30, 30)) % 360,
                            0.0, rs, top - 2.0 * rs))
        kf = min(len(dense) - 1, k + int(10 / SPACING))
        foot, foot_level = dense[kf], float(surf[kf])
        objects.append((POOL, foot[0], foot[1], yaw, 0.0, POOL_SCALE, foot_level))
        pool_half = 28.6 * POOL_SCALE
        channels.append({"kind": "pool", "center": [float(foot[0]), float(foot[1])], "radius": POOL_RADIUS,
                         "level": foot_level, "depth": POOL_DEPTH, "bank": POOL_BANK, "shore": 2.5,
                         "reach": pool_half * math.sqrt(2) + EDGE_DIAG})
        for _ in range(6):
            p = foot + nrm * rng.uniform(-POOL_RADIUS, POOL_RADIUS) + d * rng.uniform(-POOL_RADIUS, POOL_RADIUS)
            objects.append((rng.choice(STONES[:1] + ["stone6_moss", "stone7_moss", "stone8_moss"]), p[0], p[1],
                            rng.uniform(0, 360), 0.0, rng.uniform(0.8, 1.6), foot_level - POOL_DEPTH))
        fall_report.append((name, "%s, about %d m: boulders scaled %.1f, pool at the foot" % (cls, height, rs)))

    # The ground: beds, banks, then every sheet edge buried.
    elev = nat.copy()
    bed_t, bank_t, _ = channel_targets(elev.shape, channels)
    inner = apply_targets(elev, bed_t, bank_t)
    sheets = sheet_transforms([(t, x, z, yaw, pitch, 0.0, sc, h) for t, x, z, yaw, pitch, sc, h in objects])
    left_e, left_m = solve_ground(elev, sheets, np.zeros(elev.shape, bool), inner, base=nat)

    # Write: heights relative to the shaped ground, which build_world will use.
    np.save(os.path.join(out, "elevation.npy"), elev.astype(np.float32))
    with open(os.path.join(out, "tb_water.txt"), "w", newline="\n") as fh:
        for tpl, x, z, yaw, pitch, scale, absolute in objects:
            rel = absolute - bilinear(elev, x / cell, z / cell)
            fh.write('"%s";%.3f;%.3f;%.3f;%.3f;0.000;%.3f;%.3f;\n' % (tpl, x + EASTING, z, yaw, pitch, scale, rel))
    # The same with absolute heights, for tools/road_build.py, which carves the roads
    # afterwards and rewrites tb_water.txt relative to that ground.
    with open(os.path.join(out, "water_abs.json"), "w") as fh:
        json.dump([[tpl, round(x, 3), round(z, 3), round(yaw, 3), round(pitch, 3), 0.0, round(scale, 4), round(absolute, 3)]
                   for tpl, x, z, yaw, pitch, scale, absolute in objects], fh)
    with open(os.path.join(out, "channels.json"), "w") as fh:
        json.dump(channels, fh)
    with open(os.path.join(out, "lines.json"), "w") as fh:
        json.dump([{"points": [list(map(float, p)) for p in ln["points"]], "class": ln["class"], "name": ln["name"],
                    "id": ln["id"]} for ln in lines], fh)

    change = elev - nat
    with open(os.path.join(out, "summary.txt"), "w", newline="\n") as fh:
        fh.write("Water from OpenStreetMap (c) OpenStreetMap contributors, ODbL.\n\n")
        fh.write("waterways by class:\n")
        for cls in CLASS_ORDER:
            extra = "" if cls in CLASSES else "  (streambed only)"
            if cls in CLASSES:
                extra = "  sheets at %.2f scale (%.1f m wide), channel %.1f m either side, bed %.1f m, banks %.1f m" % (
                    sheet_scale(cls), 2 * CLASSES[cls][1] * sheet_scale(cls), CLASSES[cls][2], CLASSES[cls][3],
                    CLASSES[cls][4])
            fh.write("  %-9s %7.1f km%s\n" % (cls, metres.get(cls, 0) / 1000, extra))
        fh.write("\nfitted to the valley floor: moved off OSM's line median %.1f m, 90%% %.1f m, %.1f%% at the %d m limit\n"
                 % (np.median(moved), np.percentile(moved, 90), 100 * (moved >= FIT_REACH - 0.5).mean(), FIT_REACH))
        fh.write("  pinned under bridges: %d crossings; ends pinned onto the creek they join: %d\n"
                 % (pinned_bridges, pinned_ends))
        fh.write("  stretches that ran into a creek already laid end on it there: %d; lines wholly on one, "
                 "dropped: %d\n" % (joined, dropped))
        fh.write("\nobjects:\n")
        for name in sorted(pieces_n):
            fh.write("  %-20s %6d\n" % (name, pieces_n[name]))
        fh.write("  %-20s %6d\n" % ("total", len(objects)))
        fh.write("  (%d ways joined into %d lines; %d short parts cover bends over %g degrees)\n"
                 % (n_ways, len(lines), covers, COVER_TURN))
        fh.write("\nground lowered at %d grid points (max %.1f m), raised at %d (max %.1f m)\n"
                 % (int((change < -0.01).sum()), -change.min(), int((change > 0.01).sum()), change.max()))
        fh.write("after shaping: %d sheet edge points still under the water's level, %d middle points with the "
                 "ground too high\n" % (left_e, left_m))
        fh.write("\nponds (moved onto the terrain's own hollows: median %.1f m, most %.1f m):\n"
                 % (float(np.median(pond_moves)) if pond_moves else 0.0, max(pond_moves) if pond_moves else 0.0))
        for n, tiles, level in pond_report:
            fh.write("  %-30s %3d tiles at %.1f m\n" % (n, tiles, level))
        fh.write("\nwaterfalls:\n")
        for n, what in fall_report:
            fh.write("  %-24s %s\n" % (n, what))
    print(open(os.path.join(out, "summary.txt")).read())


if __name__ == "__main__":
    main()
