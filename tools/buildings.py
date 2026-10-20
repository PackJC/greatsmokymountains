"""Buildings, cabins, sheds, fuel stations, fences, guardrails and bridges.

    python tools/buildings.py <elevation .npy> source tools/georef.json source/buildings

Reads source/buildings/ (osm_buildings.json, osm_barriers.json, catalog.json,
bridge_decks.json), source/roads/lines.json, source/water/lines.json,
source/rocks/tb_rocks.txt and source/mask.png. Writes into source/buildings/:
  tb_buildings.txt   every OpenStreetMap building as the closest vanilla model of its
                     kind, turned to its footprint; big resorts get several
  tb_cabins.txt      cabins (and some sheds) along residential streets where OSM maps
                     no buildings: the rental-cabin hills round Gatlinburg
  tb_fuel.txt        the fuel stations: canopy, kiosk, working pumps
  tb_fences.txt      OSM fences, walls and hedges, and crash barriers on main roads
                     wherever the ground drops away steeply beside them
  tb_bridges.txt     a bridge model on every bridged road and trail span
  footprints.json    every footprint (for clearing trees and rocks, and painting the mask)
  elevation.npy      the heights with a level pad under every building
  summary.txt
Buildings stand on their model's own base on the pad. Bridges sit so their
deck meets the road at both ends, from deck heights measured on the vanilla
maps (tools/bridge_decks.py).
"""

import json
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import utm  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
EASTING = 200000.0
SIZE = 20480
CELL = 5.0
CLEAR_RES = 2.0
PAD_CORE = 5.0                   # flat ring around a footprint, so the ground under it is level
PAD_BLEND = 8.0                  # then back to the ground over this
MAX_CABIN_RISE = 7.0             # skip a cabin site whose ground rises more than this across it
MAX_PAD_CUT = 8.0                # a pad never moves the ground more than this (big hillside buildings)
GUARD_DROP = 5.0                 # crash barriers where the ground falls this much within 8 m of the road edge
GUARD_RUN = 4                    # ...for at least this many barrier pieces in a row

POOLS = {
    "house": ["house_1w01", "house_1w02", "house_1w03", "house_1w04", "house_1w05", "house_1w05_yellow", "house_1w06",
              "house_1w07", "house_1w08", "house_1w08_brown", "house_1w09", "house_1w09_yellow", "house_1w10",
              "house_1w10_brown", "house_1w11", "house_1w12", "house_1w12_brown", "house_2w01", "house_2w02",
              "house_2w03", "house_2w03_brown", "house_2w04", "house_2w04_yellow", "house_2b01", "house_2b04"],
    "cabin": ["house_1w01", "house_1w02", "house_1w03", "house_1w04", "house_1w05", "house_1w06", "house_1w07",
              "house_1w08_brown", "house_1w09", "house_1w10_brown", "house_1w11", "house_1w12_brown", "house_2w01",
              "house_2w02", "house_2w03_brown", "house_2w04"],
    "hotel": ["hotel", "tenement_small", "houseblock_3f1", "houseblock_3f2", "houseblock_2f2", "houseblock_2f3",
              "houseblock_2f8", "houseblock_5f"],
    "commercial": ["city_store", "city_store_withstairs", "village_store", "village_store_enoch", "office1", "office2",
                   "house_1b01_pub", "village_pub", "houseblock_1f1", "houseblock_1f2", "houseblock_1f3",
                   "houseblock_1f4", "houseblock_2f1", "houseblock_2f4", "houseblock_2f6", "garage_office"],
    "church": ["chapel", "church1_yellow", "church2_1", "church2_2", "church3"],
    "school": ["city_school"],
    "police": ["city_policestation", "village_policestation"],
    "fire": ["city_firestation"],
    "medical": ["village_healthcare", "city_hospital"],
    "garage": ["garage_small", "garage_row_small", "garage_row_big", "garage_big", "garage_medium", "garage_tall"],
    "shed": ["shed_m1", "shed_m3", "shed_m4", "shed_w1", "shed_w2", "shed_w3", "shed_w5", "shed_w6",
             "shed_closed_small1", "shed_closed_small2"],
    "barn": ["barn_wood1", "barn_wood2", "barn_brick1", "barn_brick2", "farm_cowsheda", "farm_cowshedb",
             "farm_cowshedc"],
    "industrial": ["workshop1", "workshop2", "workshop3", "workshop4", "workshop5", "factory_small", "shed_closed",
                   "repair_center"],
}
SURFACE = {"house": "cp_dirt", "cabin": "cp_dirt", "shed": "cp_dirt", "barn": "cp_dirt"}   # others: cp_concrete1
HOUSE_TYPES = {"house", "residential", "detached", "semidetached_house", "bungalow", "cabin", "terrace"}
SKIP_TYPES = {"no", "ruins", "construction", "grandstand", "roof", "parking", "bridge", "proposed"}

BRIDGE = {   # model, span axis, width (m), span length (m) at scale 1
    "stone": ("bridge_stone_25", "z"), "concrete1": ("bridge_concrete1_25", "z"),
    "concrete2": ("bridge_concrete2_25", "z"), "wood": ("bridge_wood_25", "x"),
}
DECK_DEFAULT = {"bridge_concrete1_25": 2.9, "bridge_wood_25": 1.77}
GUARD = "misc_crashbarrier"
FENCE = {"town": "wall_wood2_5", "field": "wall_fen1_5", "wall": "wall_stone", "hedge": "b_corylusheterophylla_2s_summer"}
ROAD_HALF = {"asf1": 6, "asf2": 4.5, "asf3": 3.5, "grav": 3, "mud": 2.5, "trail": 1.2}
WATER_HALF = {"river": 10.5, "stream": 7, "brook": 6.5, "seasonal": 1}   # the water sheets' reach (tools/osm_water.py)
OVERLAP_SLACK = 0.25             # models may touch by this much (bounding boxes include eaves and steps)
SHIFTS = [(0, 0), (0, 1), (0, -1), (1, 0), (-1, 0), (0, 2), (0, -2), (2, 0), (-2, 0), (1, 1), (-1, -1)]


def hull(points):
    pts = sorted(set(map(tuple, points)))
    if len(pts) < 3:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def min_rect(points):
    """Smallest rotated rectangle: centre, long side, short side, long-axis heading (deg from north)."""
    h = np.array(hull(points), float)
    best = None
    for k in range(len(h)):
        e = h[(k + 1) % len(h)] - h[k]
        n = math.hypot(*e)
        if n < 1e-6:
            continue
        u = e / n
        v = np.array([-u[1], u[0]])
        a, b = h @ u, h @ v
        area = (a.max() - a.min()) * (b.max() - b.min())
        if best is None or area < best[0]:
            c = u * (a.max() + a.min()) / 2 + v * (b.max() + b.min()) / 2
            best = (area, c, a.max() - a.min(), b.max() - b.min(), u)
    _, c, la, lb, u = best
    if lb > la:
        la, lb, u = lb, la, np.array([-u[1], u[0]])
    return c, la, lb, math.degrees(math.atan2(u[0], u[1])) % 180


def rect_corners(c, length, width, heading):
    a = math.radians(heading)
    u = np.array([math.sin(a), math.cos(a)])
    v = np.array([u[1], -u[0]])
    return [tuple(c + u * su * length / 2 + v * sv * width / 2) for su, sv in ((1, 1), (1, -1), (-1, -1), (-1, 1))]


def model_rect(c, yaw, m, grow=0.0):
    """Corners of a placed model's footprint: its x size (w) across, its z size (l)
    along its yaw, centred on its position (the model's bounding centre)."""
    a = math.radians(yaw)
    d = np.array([math.sin(a), math.cos(a)])
    r = np.array([math.cos(a), -math.sin(a)])
    hl, hw = m["l"] / 2 + grow, m["w"] / 2 + grow
    c = np.asarray(c, float)
    return np.array([c + d * hl + r * hw, c + d * hl - r * hw, c - d * hl - r * hw, c - d * hl + r * hw])


def overlap(a, b):
    """Two convex quads overlap (separating axis test)."""
    for poly in (a, b):
        for k in range(4):
            e = poly[(k + 1) % 4] - poly[k]
            ax = np.array([-e[1], e[0]])
            pa, pb = a @ ax, b @ ax
            if pa.max() <= pb.min() or pb.max() <= pa.min():
                return False
    return True


class Rects:
    """Footprints of the models placed so far, so no model goes into another."""

    def __init__(self, cell=30.0):
        self.cell, self.grid, self.items = cell, {}, []

    def _keys(self, q):
        lo, hi = q.min(axis=0) // self.cell, q.max(axis=0) // self.cell
        return [(i, j) for i in range(int(lo[0]), int(hi[0]) + 1) for j in range(int(lo[1]), int(hi[1]) + 1)]

    def hits(self, q):
        seen = set()
        for key in self._keys(q):
            for k in self.grid.get(key, ()):
                if k not in seen:
                    seen.add(k)
                    if overlap(q, self.items[k]):
                        return True
        return False

    def add(self, q):
        self.items.append(q)
        for key in self._keys(q):
            self.grid.setdefault(key, []).append(len(self.items) - 1)


def wide_line(draw, pts, width, fill=1):
    """A wide polyline with a disc on every point: PIL's own leaves pixel cracks at its
    joints (and square ends)."""
    draw.line(pts, fill=fill, width=width, joint="curve")
    r = width / 2.0
    if width > 2:
        for cx, cz in pts:
            draw.ellipse([cx - r, cz - r, cx + r, cz + r], fill=fill)


def sample(grid, x, z):
    fx, fz = x / CELL, z / CELL
    x0 = min(max(int(fx), 0), grid.shape[1] - 2)
    z0 = min(max(int(fz), 0), grid.shape[0] - 2)
    tx, tz = fx - x0, fz - z0
    return float(grid[z0, x0] * (1 - tx) * (1 - tz) + grid[z0, x0 + 1] * tx * (1 - tz)
                 + grid[z0 + 1, x0] * (1 - tx) * tz + grid[z0 + 1, x0 + 1] * tx * tz)


def main():
    elev_path, src, georef_path, out = sys.argv[1:5]
    bdir = out
    rng = random.Random(2812533524 + 3)
    elev0 = np.load(elev_path).astype(np.float64)
    elev = elev0.copy()
    geo = json.load(open(georef_path))
    ox, oy = geo["offset_x"], geo["offset_y"]
    cat = {r["name"]: r for r in json.load(open(os.path.join(bdir, "catalog.json"))) if "\\proxy\\" not in r["path"]}
    decks = {k: v["deck"] for k, v in json.load(open(os.path.join(bdir, "bridge_decks.json"))).items()}
    decks.update({k: v for k, v in DECK_DEFAULT.items() if k not in decks})
    decks["bridge_wood_50"] = decks["bridge_wood_25"]

    def to_map(p):
        x, y = utm(p["lat"], p["lon"], 17)
        return x + ox, y + oy

    roads = json.load(open(os.path.join(src, "roads", "lines.json")))
    water = json.load(open(os.path.join(src, "water", "lines.json")))
    mask = np.asarray(Image.open(os.path.join(src, "mask.png")).convert("RGB").resize((2560, 2560), Image.NEAREST))
    town = (mask[..., 0] == 120) & (mask[..., 1] == 200) & (mask[..., 2] == 60)

    def in_town(x, z):
        return bool(town[min(2559, max(0, int((SIZE - z) / 8))), min(2559, max(0, int(x / 8)))])

    # Keep-clear map at 2 m: roads, creeks, rocks; footprints are added as they're placed.
    n2 = int(SIZE / CLEAR_RES)
    clear_img = Image.new("1", (n2, n2), 0)
    dc = ImageDraw.Draw(clear_img)
    road_img = Image.new("1", (n2, n2), 0)
    dr = ImageDraw.Draw(road_img)

    def px(points):
        return [(x / CLEAR_RES, (SIZE - z) / CLEAR_RES) for x, z in points]
    for ln in roads:
        w = max(1, int(round(2 * (ROAD_HALF[ln["family"]] + 2.0) / CLEAR_RES)))
        wide_line(dc, px(ln["points"]), w)
        wide_line(dr, px(ln["points"]), max(1, int(round(2 * (ROAD_HALF[ln["family"]] + 1.0) / CLEAR_RES))))
    for ln in water:
        wide_line(dc, px(ln["points"]), max(1, int(round(2 * (WATER_HALF[ln["class"]] + 1.0) / CLEAR_RES))))
    for raw in open(os.path.join(src, "rocks", "tb_rocks.txt")):
        p = raw.split(";")
        x, z, s = float(p[1]) - EASTING, float(p[2]), float(p[6])
        r = 3.0 * s / CLEAR_RES
        c = (x / CLEAR_RES, (SIZE - z) / CLEAR_RES)
        dc.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=1)
    clear = np.array(clear_img)
    road_keep = np.asarray(road_img)
    # The road surfaces as built (tools/road_build.py), and the trails: no building
    # may stand on them.
    built_path = os.path.join(src, "roads", "centerlines.json")
    built = json.load(open(built_path)) if os.path.isfile(built_path) else []
    surf_img = Image.new("1", (n2, n2), 0)
    ds = ImageDraw.Draw(surf_img)
    for cl in built:
        q = px([(p[0], p[1]) for p in cl["points"]])
        ds.line(q, fill=1, width=max(1, int(round(2 * ROAD_HALF[cl["family"]] / CLEAR_RES))), joint="curve")
        r = ROAD_HALF[cl["family"]] / CLEAR_RES
        for cx, cz in q:                           # every point: no cracks at the joints, round ends
            ds.ellipse([cx - r, cz - r, cx + r, cz + r], fill=1)
    for ln in roads:
        if ln["family"] == "trail" or not built:
            wide_line(ds, px(ln["points"]), max(1, int(round(2 * ROAD_HALF[ln["family"]] / CLEAR_RES))))
    road_surf = np.asarray(surf_img)
    rects = Rects()
    # The same surfaces as points with half widths, for exact tests along lines.
    rp, rh, ro = [], [], []
    for i, cl in enumerate(built):
        q = np.asarray([p[:2] for p in cl["points"]], float)
        if len(q) < 2:
            continue
        seg_l = np.hypot(*np.diff(q, axis=0).T)
        s_l = np.r_[0, np.cumsum(seg_l)]
        f = np.arange(0, s_l[-1] + 1e-6, 1.0)
        q = np.c_[np.interp(f, s_l, q[:, 0]), np.interp(f, s_l, q[:, 1])]
        rp.append(q)
        rh.append(np.full(len(q), ROAD_HALF[cl["family"]]))
        ro.append(np.full(len(q), i))
    if rp:
        from scipy.spatial import cKDTree
        r_pts, r_half, r_own = np.vstack(rp), np.concatenate(rh), np.concatenate(ro)
        r_tree = cKDTree(r_pts)

    def road_under(pt, margin, exclude=-1):
        """Is the point on a built road's surface (within margin), other than road `exclude`?"""
        if not rp:
            return False
        d, k = r_tree.query(pt, k=12, distance_upper_bound=15.0)
        ok = np.isfinite(d)
        k = np.where(ok, k, 0)
        return bool((ok & (d <= r_half[k] + margin) & (r_own[k] != exclude)).any())

    def on_road(q):
        xs, zs = q[:, 0], q[:, 1]
        c0, c1 = int(xs.min() / CLEAR_RES), int(xs.max() / CLEAR_RES) + 1
        r0, r1 = int((SIZE - zs.max()) / CLEAR_RES), int((SIZE - zs.min()) / CLEAR_RES) + 1
        if c0 < 0 or r0 < 0 or c1 > n2 or r1 > n2:
            return True
        sub = Image.new("1", (c1 - c0, r1 - r0), 0)
        ImageDraw.Draw(sub).polygon([(x / CLEAR_RES - c0, (SIZE - z) / CLEAR_RES - r0) for x, z in q], fill=1)
        return bool((np.asarray(sub) & road_surf[r0:r1, c0:c1]).any())
    water_keep = np.zeros((elev.shape[0], elev.shape[1]), bool)
    wimg = Image.new("1", (elev.shape[1], elev.shape[0]), 0)
    dw = ImageDraw.Draw(wimg)
    for ln in water:
        wide_line(dw, [(x / CELL, z / CELL) for x, z in ln["points"]], max(1, int(round(2 * (WATER_HALF[ln["class"]] + 2) / CELL))))
    water_keep = np.asarray(wimg)                     # south-origin, like elev

    def footprint_clear(corners):
        xs = [c[0] for c in corners]
        zs = [c[1] for c in corners]
        c0, c1 = int(min(xs) / CLEAR_RES), int(max(xs) / CLEAR_RES) + 1
        r0, r1 = int((SIZE - max(zs)) / CLEAR_RES), int((SIZE - min(zs)) / CLEAR_RES) + 1
        if c0 < 0 or r0 < 0 or c1 > n2 or r1 > n2:
            return False
        sub = Image.new("1", (c1 - c0, r1 - r0), 0)
        ImageDraw.Draw(sub).polygon([(x / CLEAR_RES - c0, (SIZE - z) / CLEAR_RES - r0) for x, z in corners], fill=1)
        return not (np.asarray(sub) & clear[r0:r1, c0:c1]).any()

    def block(corners, margin=2.0):
        """Mark a footprint (grown by margin) as taken, drawing only its own window."""
        c = np.mean(corners, axis=0)
        grown = [tuple(c + (np.array(p) - c) * (1 + margin / max(1.0, np.hypot(*(np.array(p) - c))))) for p in corners]
        xs = [p[0] for p in grown]
        zs = [p[1] for p in grown]
        c0, c1 = max(0, int(min(xs) / CLEAR_RES)), min(n2, int(max(xs) / CLEAR_RES) + 2)
        r0, r1 = max(0, int((SIZE - max(zs)) / CLEAR_RES)), min(n2, int((SIZE - min(zs)) / CLEAR_RES) + 2)
        if c1 <= c0 or r1 <= r0:
            return
        sub = Image.new("1", (c1 - c0, r1 - r0), 0)
        ImageDraw.Draw(sub).polygon([(x / CLEAR_RES - c0, (SIZE - z) / CLEAR_RES - r0) for x, z in grown], fill=1)
        clear[r0:r1, c0:c1] |= np.asarray(sub)

    footprints, files, counts = [], {}, {}
    for k in ("buildings", "cabins", "fuel", "fences", "bridges"):
        files[k] = open(os.path.join(bdir, "tb_%s.txt" % k), "w", newline="\n")

    def emit(kind, name, x, z, yaw, rel, pitch=0.0, roll=0.0, scale=1.0):
        files[kind].write('"%s";%.3f;%.3f;%.2f;%.3f;%.3f;%.3f;%.3f;\n'
                          % (name, x + EASTING, z, yaw % 360, pitch, roll, scale, rel))
        counts[kind] = counts.get(kind, 0) + 1

    def pad(corners, allow_rise=None):
        """Level the ground under a footprint. Returns the pad height, or None if the
        site rises more than allow_rise across it."""
        c = np.mean(corners, axis=0)
        xs = [p[0] for p in corners]
        zs = [p[1] for p in corners]
        reach = PAD_CORE + PAD_BLEND
        i0, i1 = int((min(xs) - reach) / CELL), int((max(xs) + reach) / CELL) + 1
        j0, j1 = int((min(zs) - reach) / CELL), int((max(zs) + reach) / CELL) + 1
        i0, j0, i1, j1 = max(i0, 0), max(j0, 0), min(i1, elev.shape[1] - 1), min(j1, elev.shape[0] - 1)
        ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1))
        gx, gz = ii * CELL, jj * CELL
        # distance from each grid node to the footprint rectangle
        poly = np.array(corners)
        u = poly[0] - poly[3]
        v = poly[0] - poly[1]
        lu, lv = np.hypot(*u), np.hypot(*v)
        u, v = u / lu, v / lv
        du = np.abs((gx - c[0]) * u[0] + (gz - c[1]) * u[1]) - lu / 2
        dv = np.abs((gx - c[0]) * v[0] + (gz - c[1]) * v[1]) - lv / 2
        d = np.hypot(np.maximum(du, 0), np.maximum(dv, 0))
        inside = d <= PAD_CORE
        if not inside.any():
            return None
        ground = elev[jj, ii]
        level = float(np.median(ground[d <= 0.5])) if (d <= 0.5).any() else float(np.median(ground[inside]))
        if allow_rise is not None and (ground[inside].max() - ground[inside].min()) > allow_rise:
            return None
        t = np.clip((d - PAD_CORE) / PAD_BLEND, 0, 1)
        new = level + (ground - level) * t
        new = np.clip(new, ground - MAX_PAD_CUT, ground + MAX_PAD_CUT)
        keep = road_keep[np.clip(((SIZE - gz) / CLEAR_RES).astype(int), 0, n2 - 1),
                         np.clip((gx / CLEAR_RES).astype(int), 0, n2 - 1)] | water_keep[jj, ii]
        new = np.where(keep & ~inside, ground, new)
        elev[jj, ii] = np.where(d <= reach, new, ground)
        return level

    # Objects wait here with absolute heights; they're written relative to the final
    # ground once every pad is cut. (kind, name, x, z, yaw, absolute y, pitch, roll, scale)
    pending = []

    def ranked(pool, length, width):
        """The pool's models, best fit to a length x width footprint first."""
        scored = []
        for name in pool:
            if name not in cat:
                continue
            m = cat[name]
            lm, wm = max(m["w"], m["l"]), min(m["w"], m["l"])
            cost = abs(math.log(lm / max(length, 1))) + abs(math.log(wm / max(width, 1)))
            scored.append((cost, name))
        scored.sort()
        return [name for _, name in scored]

    def fit_model(pool, length, width, p0, heading, u, v):
        """A model for a footprint cell that stands clear of every model placed so far
        and of the roads: one of the three best fits (for variety), else the next
        best, else smaller ones, each at the cell's centre or moved up to 2 m.
        Returns (name, position, yaw) or None."""
        order = ranked(pool, length, width)
        best = order[:3]
        rng.shuffle(best)
        rest = sorted(order[3:], key=lambda nm: cat[nm]["w"] * cat[nm]["l"])
        for nm in best + rest:
            m = cat[nm]
            yaw = heading if m["l"] >= m["w"] else heading + 90
            for su, sv in SHIFTS:
                p = p0 + u * su + v * sv
                q = model_rect(p, yaw, m, -OVERLAP_SLACK)
                if not rects.hits(q) and not on_road(q):
                    rects.add(q)
                    return nm, p, yaw
        return None

    # ---- OSM buildings ----
    # Biggest first, so a hotel isn't crowded out by the sheds round it. Every model
    # must stand clear of the models already placed and of the road surfaces.
    elements = json.load(open(os.path.join(bdir, "osm_buildings.json"), encoding="utf-8"))["elements"]
    by_kind = {}
    osm_centres = []
    osm_dropped = osm_shrunk = 0
    found = []
    for e in elements:
        t = e.get("tags", {})
        geom = e.get("geometry") or [p for mm in e.get("members", []) if mm.get("role") == "outer"
                                     for p in (mm.get("geometry") or [])]
        pts = [to_map(p) for p in geom if p]
        if len(pts) < 3 or not all(20 < x < SIZE - 20 and 20 < z < SIZE - 20 for x, z in pts):
            continue
        b = t.get("building", "yes")
        amen = t.get("amenity", "")
        if b in SKIP_TYPES or amen == "fuel":
            continue
        c, length, width, heading = min_rect(pts)
        found.append((length * width, t, b, amen, c, length, width, heading))
    found.sort(key=lambda f: -f[0])
    for area, t, b, amen, c, length, width, heading in found:
        if amen in ("fire_station",):
            kind = "fire"
        elif amen in ("police", "ranger_station"):
            kind = "police"
        elif amen in ("clinic", "hospital", "doctors"):
            kind = "medical"
        elif b in ("church", "chapel", "cathedral") or amen == "place_of_worship":
            kind = "church"
        elif b in ("school", "college", "university", "kindergarten"):
            kind = "school"
        elif b in ("hotel", "apartments", "dormitory") or t.get("tourism") in ("hotel", "motel"):
            kind = "hotel" if area > 300 else "commercial"
        elif b in ("retail", "commercial", "office", "supermarket", "kiosk") or amen or t.get("shop"):
            kind = "commercial" if area > 60 else "shed"
        elif b in ("garage", "garages", "carport"):
            kind = "garage"
        elif b in ("shed", "hut", "greenhouse", "toilets", "service"):
            kind = "shed"
        elif b in ("barn", "farm_auxiliary", "stable", "cowshed"):
            kind = "barn"
        elif b in HOUSE_TYPES:
            kind = "house" if area > 35 else "shed"
        else:                                         # "yes" and the rest, by size
            kind = "shed" if area < 35 else "house" if area < 260 else "commercial" if area < 1800 else "hotel"
        order = ranked(POOLS[kind], length, width)
        if not order:
            continue
        m0 = cat[order[0]]
        lm, wm = max(m0["w"], m0["l"]), min(m0["w"], m0["l"])
        rows = cols = 1
        if kind in ("commercial", "hotel") and area > 2.2 * lm * wm:
            cols = int(min(4, max(1, round(length / lm))))
            rows = int(min(2, max(1, round(width / wm))))
        a = math.radians(heading)
        u = np.array([math.sin(a), math.cos(a)])
        v = np.array([u[1], -u[0]])
        chosen = []
        for ci in range(cols):
            for ri in range(rows):
                p0 = c + u * (ci - (cols - 1) / 2) * (length / cols) + v * (ri - (rows - 1) / 2) * (width / rows)
                got = fit_model(POOLS[kind], length / cols, width / rows, p0, heading, u, v)
                if got:
                    chosen.append(got)
        if not chosen:
            osm_dropped += 1
            continue
        if len(chosen) < rows * cols:
            osm_shrunk += 1
        # Level the ground under the footprint and the models together.
        allpts = np.vstack([np.array(rect_corners(c, length, width, heading))]
                           + [model_rect(p, yaw, cat[nm]) for nm, p, yaw in chosen])
        pc, pl, pw, ph = min_rect([tuple(p) for p in allpts])
        corners = rect_corners(pc, pl, pw, ph)
        level = pad(corners)
        if level is None:
            continue
        for nm, p, yaw in chosen:
            mm = cat[nm]
            pending.append(("buildings", nm, p[0], p[1], yaw + rng.choice((0, 180)), level + mm["center"][1],
                            0.0, 0.0, 1.0))
            by_kind[kind] = by_kind.get(kind, 0) + 1
        footprints.append({"corners": corners, "kind": kind, "surface": SURFACE.get(kind, "cp_concrete1")})
        block(corners)
        osm_centres.append(c)

    # ---- fuel stations ----
    barriers = json.load(open(os.path.join(bdir, "osm_barriers.json"), encoding="utf-8"))["elements"]
    fuel_n = fuel_skipped = 0
    for e in barriers:
        t = e.get("tags", {})
        if t.get("amenity") != "fuel" or "geometry" not in e:
            continue
        pts = [to_map(p) for p in e["geometry"]]
        if not all(20 < x < SIZE - 20 and 20 < z < SIZE - 20 for x, z in pts):
            continue
        c, length, width, heading = min_rect(pts)
        canopy = cat["fuelstation_shed"]
        a = math.radians(heading)
        u = np.array([math.sin(a), math.cos(a)])
        v = np.array([u[1], -u[0]])
        yaw = heading if canopy["l"] >= canopy["w"] else heading + 90
        # The canopy (pumps under it) must clear the buildings; the kiosk goes beside
        # it on whichever side is free of buildings and roads, or is left out.
        spot = None
        for su, sv in SHIFTS:
            p = c + u * su * 2 + v * sv * 2
            q = model_rect(p, yaw, canopy, -OVERLAP_SLACK)
            if not rects.hits(q):
                spot = p, q
                break
        if spot is None:
            fuel_skipped += 1
            continue
        c, q = spot
        kiosk = None
        kb = cat["fuelstation_build"]
        for side in (1, -1):
            kp = c + v * side * (max(width, 18) / 2 + 2)
            kq = model_rect(kp, yaw, kb, -OVERLAP_SLACK)
            if not overlap(kq, q) and not rects.hits(kq) and not on_road(kq):
                kiosk = kp, kq
                break
        corners = rect_corners(c, max(length, 26), max(width, 18), heading)
        level = pad(corners)
        if level is None:
            continue
        rects.add(q)
        pending.append(("fuel", "fuelstation_shed", c[0], c[1], yaw, level + canopy["center"][1], 0, 0, 1))
        for k in (-1, 1):
            for s in (-1, 1):
                p = c + u * k * 4.0 + v * s * 2.0
                pending.append(("fuel", "fuelstation_feed", p[0], p[1], yaw, level + cat["fuelstation_feed"]["center"][1],
                                0, 0, 1))
        if kiosk:
            rects.add(kiosk[1])
            pending.append(("fuel", "fuelstation_build", kiosk[0][0], kiosk[0][1], yaw, level + kb["center"][1],
                            0, 0, 1))
        footprints.append({"corners": corners, "kind": "fuel", "surface": "cp_concrete1"})
        block(corners)
        fuel_n += 1

    # ---- cabins along residential streets with no mapped buildings ----
    osm_c = np.array(osm_centres) if osm_centres else np.zeros((0, 2))
    cabins = sheds = 0
    for ln in roads:
        if ln["group"] != "local" or ln["highway"] not in ("residential", "living_street", "road"):
            continue
        pts = np.asarray(ln["points"], float)
        seg = np.hypot(*np.diff(pts, axis=0).T)
        arc = np.concatenate([[0], np.cumsum(seg)])
        s, side = rng.uniform(10, 40), rng.choice((-1, 1))
        while s < arc[-1] - 10:
            k = min(int(np.searchsorted(arc, s)), len(pts) - 2)
            d = pts[k + 1] - pts[k]
            d = d / (np.hypot(*d) or 1)
            nrm = np.array([-d[1], d[0]]) * side
            p = pts[k] + d * (s - arc[k])
            if rng.random() < 0.7 and (len(osm_c) == 0 or np.hypot(*(osm_c - p).T).min() > 45):
                name = rng.choice(POOLS["cabin"])
                m = cat[name]
                lm, wm = max(m["w"], m["l"]), min(m["w"], m["l"])
                setback = ROAD_HALF[ln["family"]] + 4 + wm / 2 + rng.uniform(0, 4)
                c = p + nrm * setback
                heading = math.degrees(math.atan2(d[0], d[1])) % 180
                corners = rect_corners(c, lm + 1, wm + 1, heading)
                yaw = heading if m["l"] >= m["w"] else heading + 90
                cq = model_rect(c, yaw, m, -OVERLAP_SLACK)
                if footprint_clear(corners) and not rects.hits(cq) and not on_road(cq):
                    level = pad(corners, allow_rise=MAX_CABIN_RISE)
                    if level is not None:
                        rects.add(cq)
                        pending.append(("cabins", name, c[0], c[1], yaw + rng.choice((0, 180)), level + m["center"][1],
                                        0, 0, 1))
                        footprints.append({"corners": corners, "kind": "cabin", "surface": "cp_dirt"})
                        block(corners, 3.0)
                        cabins += 1
                        if rng.random() < 0.25:
                            sname = rng.choice(POOLS["shed"][:8])
                            sm = cat[sname]
                            sc = c + nrm * (wm / 2 + 5) + d * rng.uniform(-lm / 3, lm / 3)
                            sc_corners = rect_corners(sc, max(sm["w"], sm["l"]) + 1, min(sm["w"], sm["l"]) + 1, heading)
                            syaw = heading if sm["l"] >= sm["w"] else heading + 90
                            sq = model_rect(sc, syaw, sm, -OVERLAP_SLACK)
                            if footprint_clear(sc_corners) and not rects.hits(sq) and not on_road(sq):
                                slevel = pad(sc_corners, allow_rise=MAX_CABIN_RISE)
                                if slevel is not None:
                                    rects.add(sq)
                                    pending.append(("cabins", sname, sc[0], sc[1], syaw, slevel + sm["center"][1],
                                                    0, 0, 1))
                                    footprints.append({"corners": sc_corners, "kind": "shed", "surface": "cp_dirt"})
                                    block(sc_corners, 1.0)
                                    sheds += 1
            s += rng.uniform(45, 70)
            side = -side

    # ---- fences, walls, hedges from OSM ----
    fence_m = {"fence": 0.0, "wall": 0.0, "hedge": 0.0}
    fence_skipped = 0
    for e in barriers:
        t = e.get("tags", {})
        bk = t.get("barrier")
        if bk not in ("fence", "wall", "retaining_wall", "city_wall", "hedge") or "geometry" not in e:
            continue
        pts = np.array([to_map(p) for p in e["geometry"]])
        kind = "hedge" if bk == "hedge" else "wall" if "wall" in bk else "fence"
        for a_, b_ in zip(pts[:-1], pts[1:]):
            seg_len = math.hypot(*(b_ - a_))
            if seg_len < 0.5:
                continue
            u = (b_ - a_) / seg_len
            if kind == "hedge":
                name, step = FENCE["hedge"], 2.5
            else:
                name = FENCE["wall"] if kind == "wall" else FENCE["town" if in_town(*a_) else "field"]
                step = max(cat[name]["w"], cat[name]["l"])
            nseg = max(1, int(round(seg_len / step)))
            for q in range(nseg):
                c = a_ + u * (q + 0.5) * seg_len / nseg
                if rects.hits(np.array([c + (0.2, 0.2), c + (0.2, -0.2), c + (-0.2, -0.2), c + (-0.2, 0.2)])):
                    fence_skipped += 1                           # no fence through a building
                    continue
                half_piece = u * seg_len / nseg / 2
                if any(road_under(q, 0.5) for q in (c, c - half_piece, c + half_piece)):
                    fence_skipped += 1                           # nor across a road
                    continue
                yaw = math.degrees(math.atan2(-u[1], u[0]))      # model x along the line
                pending.append(("fences", name, c[0], c[1], yaw, sample(elev, c[0], c[1]) + cat.get(name, {"center": [0, 0, 0]})["center"][1],
                                0, 0, 1))
            fence_m[kind] += seg_len

    # ---- crash barriers where main roads have a steep drop beside them ----
    guard = cat[GUARD]
    glen = guard["w"]
    guards = 0
    # Along the roads as built (their level ground reaches 6 m past the edge, so the
    # drop is measured 8 m beyond that).
    guard_lines = built or [ln for ln in roads if not ln["bridge"]]
    for li, ln in enumerate(guard_lines):
        if ln["group"] != "main" or ln["family"] not in ("asf1", "asf2", "asf3") or ln.get("bridge"):
            continue
        pts = np.asarray([p[:2] for p in ln["points"]], float)
        if len(pts) < 2:
            continue
        seg = np.hypot(*np.diff(pts, axis=0).T)
        keep = np.r_[True, seg > 1e-6]
        pts = pts[keep]
        seg = np.hypot(*np.diff(pts, axis=0).T)
        arc = np.concatenate([[0], np.cumsum(seg)])
        half = ROAD_HALF[ln["family"]]
        reach = half + (14.0 if built else 8.0)
        for side in (-1, 1):
            run = []
            s = glen / 2
            while s < arc[-1]:
                k = min(int(np.searchsorted(arc, s)), len(pts) - 2)
                d = pts[k + 1] - pts[k]
                d = d / (np.hypot(*d) or 1)
                nrm = np.array([-d[1], d[0]]) * side
                p = pts[k] + d * (s - arc[k])
                drop = sample(elev0, *p) - sample(elev0, *(p + nrm * reach))
                gq = p + nrm * (half + 0.6)
                # a run stops where a side road leaves: no barrier across its mouth
                ends_free = not any(road_under(q, 0.5, exclude=li if built else -1)
                                    for q in (gq, gq - d * glen / 2, gq + d * glen / 2))
                if drop > GUARD_DROP and ends_free:
                    run.append((gq, d))
                else:
                    if len(run) >= GUARD_RUN:
                        for q, dd in run:
                            yaw = math.degrees(math.atan2(-dd[1], dd[0]))
                            pending.append(("fences", GUARD, q[0], q[1], yaw + (180 if side < 0 else 0),
                                            sample(elev0, *q) + guard["center"][1], 0, 0, 1))
                            guards += 1
                    run = []
                s += glen
            if len(run) >= GUARD_RUN:
                for q, dd in run:
                    yaw = math.degrees(math.atan2(-dd[1], dd[0]))
                    pending.append(("fences", GUARD, q[0], q[1], yaw + (180 if side < 0 else 0),
                                    sample(elev0, *q) + guard["center"][1], 0, 0, 1))
                    guards += 1

    # ---- bridges ----
    bridge_n, bridge_kinds = 0, {}
    for ln in roads:
        if not ln["bridge"]:
            continue
        pts = np.asarray(ln["points"], float)
        span = float(np.hypot(*np.diff(pts, axis=0).T).sum())
        if span > 150:
            continue
        p0, p1 = pts[0], pts[-1]
        chord = p1 - p0
        L = float(np.hypot(*chord))
        if L < 2:
            continue
        u = chord / L
        h0, h1 = sample(elev0, *p0), sample(elev0, *p1)
        fam = ln["family"]
        if fam == "trail":
            key, scale = "wood", min(0.7, max(0.3, (L + 4) / 33.0))
        elif fam in ("grav", "mud"):
            key, scale = "wood", 1.0
        elif fam == "asf1":
            key, scale = "concrete2", 1.0
        else:
            key, scale = ("concrete1" if in_town(*((p0 + p1) / 2)) else "stone"), 1.0
        name, axis = BRIDGE[key]
        m = cat[name]
        seg_len = (m["w"] if axis == "x" else m["l"]) * scale
        n = max(1, int(math.ceil((L + 4) / seg_len)))
        deck = decks.get(name, 0.0) * scale
        total = n * seg_len
        slope = (h1 - h0) / L
        for q in range(n):
            along = -total / 2 + (q + 0.5) * seg_len                 # from the chord's midpoint
            c = (p0 + p1) / 2 + u * along
            t = min(1.0, max(0.0, (along + L / 2) / L))
            deck_h = h0 + (h1 - h0) * t
            if axis == "z":
                yaw = math.degrees(math.atan2(u[0], u[1]))
                pitch = math.degrees(math.atan(-slope))
                roll = 0.0
            else:
                yaw = math.degrees(math.atan2(-u[1], u[0]))
                pitch = 0.0
                roll = math.degrees(math.atan(slope))
            pending.append(("bridges", name, c[0], c[1], yaw, deck_h - deck, pitch, roll, scale))
        bridge_n += 1
        bridge_kinds[name] = bridge_kinds.get(name, 0) + 1

    # Heights were absolute: write them relative to the final ground (pads included).
    for kind, name, x, z, yaw, absolute, pitch, roll, scale in pending:
        emit(kind, name, x, z, yaw, absolute - sample(elev, x, z), pitch, roll, scale)
    for fh in files.values():
        fh.close()
    np.save(os.path.join(bdir, "elevation.npy"), elev.astype(np.float32))
    json.dump(footprints, open(os.path.join(bdir, "footprints.json"), "w"))

    changed = np.abs(elev - elev0)
    with open(os.path.join(bdir, "summary.txt"), "w", newline="\n") as fh:
        fh.write("Buildings from OpenStreetMap (c) OpenStreetMap contributors, ODbL, as vanilla models.\n\n")
        fh.write("OSM buildings by kind (models placed):\n")
        for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]):
            fh.write("  %-11s %5d\n" % (k, v))
        fh.write("\nno model overlaps another or a road: %d OSM buildings left out (no model fitted between "
                 "their neighbours), %d big ones got fewer models\n" % (osm_dropped, osm_shrunk))
        fh.write("\ncabins filled in along residential streets: %d, with %d sheds\n" % (cabins, sheds))
        fh.write("fuel stations: %d (%d left out, no room clear of buildings)\n" % (fuel_n, fuel_skipped))
        fh.write("fence pieces left out where a building stands: %d\n" % fence_skipped)
        fh.write("fences %.0f m, walls %.0f m, hedges %.0f m (OSM); crash barriers: %d pieces (%.1f km)\n"
                 % (fence_m["fence"], fence_m["wall"], fence_m["hedge"], guards, guards * glen / 1000))
        fh.write("bridges: %d spans: %s\n" % (bridge_n, ", ".join("%s %d" % kv for kv in sorted(bridge_kinds.items()))))
        fh.write("\nobjects per file:\n")
        for k in ("buildings", "cabins", "fuel", "fences", "bridges"):
            fh.write("  tb_%-10s %6d\n" % (k + ".txt", counts.get(k, 0)))
        fh.write("\nground levelled under footprints: %d height points changed, max %.1f m, median %.2f m\n"
                 % (int((changed > 0.01).sum()), changed.max(), float(np.median(changed[changed > 0.01])) if (changed > 0.01).any() else 0))
    print(open(os.path.join(bdir, "summary.txt")).read())


if __name__ == "__main__":
    main()
