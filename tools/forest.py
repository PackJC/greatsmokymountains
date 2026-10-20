"""Grow the Smokies' forests: trees, understory and deadwood over the whole map.

    python tools/forest.py <elevation .npy> source source/roads/lines.json source/water/lines.json
        source/rocks/tb_rocks.txt source/forest

Reads the carved heights, source/satellite.png (leaf-off imagery: evergreen
stands are dark green, bare hardwoods brown, towns and open ground bright) and
source/mask.png, and works on an 8 m grid. Each cell gets a forest zone:
  spruce-fir         above 1,680 m, or above 1,480 m where the imagery is evergreen
  northern hardwood  1,250 to 1,680 m: beech, birch, maple, some spruce
  cove hardwood      below 1,250 m in hollows and within 60 m of a creek: ash, tulip
                     poplar (black poplar), maple, beech, walnut, oak, hemlock (spruce)
  oak-pine           below 1,250 m on ridges and steep south-west slopes: oak, pine, locust
  mixed hardwood     the rest below 1,250 m
  open               bright, fairly flat ground in the imagery (lawns, lots, fields,
                     Gatlinburg's centre): scattered yard, orchard and field-edge
                     trees. Bright steep slopes are sun-lit forest. The rest of
                     the original map's grass (Gatlinburg's wooded hills) grows forest
                     at 70% density, keeping its grass floor.
Evergreen imagery at low elevation adds hemlock and rhododendron-like thickets.
Cliffs (over 45 degrees) keep few trees. Nothing grows on roads, trails, creek
channels or rocks.

Writes tb_trees.txt, tb_bushes.txt, tb_deadwood.txt (Terrain Builder object
imports, height relative to the ground: the model's own base on the ground,
sunk a little), zones.npy (2560 x 2560, north up, for tools/paint_roads.py) and
summary.txt. DENSITY scales every rate.
"""

import json
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from odol_info import odol_info  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
EASTING = 200000.0
SIZE = 20480
CELL = 8.0
N = int(SIZE / CELL)
DENSITY = 1.0
CLEAR_RES = 2.0

ZONES = ["open", "sprucefir", "northern", "cove", "oakpine", "mixed"]
# Forest floor per zone, for the mask: its clutter is the grass and undergrowth.
ZONE_SURFACE = {"sprucefir": "cp_conifer_moss1", "northern": "cp_broadleaf_sparse2",
                "cove": "cp_broadleaf_dense1", "oakpine": "cp_broadleaf_sparse1", "mixed": "cp_broadleaf_dense2"}
# chance of a tree / a bush / deadwood per 8 m cell
RATES = {"open": (0.05, 0.06, 0.0), "sprucefir": (0.60, 0.12, 0.05), "northern": (0.55, 0.12, 0.015),
         "cove": (0.62, 0.18, 0.015), "oakpine": (0.45, 0.15, 0.012), "mixed": (0.55, 0.12, 0.012)}

P = r"P:\DZ\plants\tree"
PB = r"P:\DZ\plants_bliss\tree"
BB = r"P:\DZ\plants_bliss\bush"
BC = r"P:\DZ\plants\bush"


def variants(folder, stem, names):
    return [os.path.join(folder, "%s_%s.p3d" % (stem, n)) for n in names]


SPECIES = {
    "spruce": variants(PB, "t_piceaabies", ["1f_summer", "1s_summer", "1sb_summer", "2f_summer", "2fb_summer",
                                            "2s_summer", "2sb_summer", "3f_summer", "3s_summer"]),
    "spruce_dead": variants(P, "t_piceaabies", ["2d", "3d"]),
    "beech": variants(PB, "t_fagussylvatica", ["1f_summer", "1fb_summer", "1fc_summer", "1fd_summer", "1fe_summer",
                                               "1s_summer", "2f_summer", "2fb_summer", "2fc_summer", "2s_summer",
                                               "2sb_summer", "3f_summer", "3fb_summer", "3s_summer"]),
    "birch": variants(PB, "t_betulapendulae", ["1s_summer", "2f_summer", "2s_summer", "2w_summer", "3f_summer",
                                               "3s_summer"]),
    "maple": variants(PB, "t_acer", ["2s_summer"]),
    "rowan": variants(PB, "t_sorbus", ["2s_summer"]),
    "oak": variants(P, "t_quercusrobur", ["1f", "1fc", "1fd", "1s", "2f", "2fb", "2fc", "2s", "2sb", "2sc", "3f",
                                          "3fb", "3s", "3sb"]),
    "pine": variants(PB, "t_pinussylvestris", ["1f_summer", "2f_summer", "2fb_summer", "2s_summer", "2sb_summer",
                                               "3f_summer", "3fb_summer", "3fc_summer", "3s_summer"]),
    "ash": variants(P, "t_fraxinusexcelsior", ["2f", "2s", "3s"]),
    "tulip": variants(PB, "t_populusnigra", ["3sb_summer"]),
    "sycamore": variants(P, "t_populusalba", ["2s", "3s"]),
    "walnut": variants(PB, "t_juglansregia", ["2s_summer", "3s_summer"]),
    "ironwood": variants(P, "t_carpinus", ["2s"]),
    "locust": variants(P, "t_robiniapseudoacacia", ["1f", "2f", "2s", "3f"]),
    "willow": variants(PB, "t_salixalba", ["2sb_summer"]),
    "apple": variants(PB, "t_malusdomestica", ["2s_summer", "3s_summer"]),
    "pear": variants(PB, "t_pyruscommunis", ["2s_summer", "3s_summer"]),
    "plum": variants(P, "t_prunusdomestica", ["2s"]),
    "yard": variants(P, "t_town", ["1s", "1sb"]),
}
BUSHES = {
    "thicket": variants(BB, "b_corylusheterophylla", ["2s_summer"]) + variants(BB, "b_sambucusnigra", ["2s_summer"])
    + variants(BB, "b_caraganaarborescens", ["2s_summer"]) + variants(P, "b_piceaabies", ["1fb"]),
    "conifer": variants(PB, "b_piceaabies", ["1f_summer", "1fb_summer"]) + variants(BB, "b_betulanana", ["1s_summer"])
    + variants(BB, "b_sambucusnigra", ["1s_summer"]),
    "hardwood": variants(BB, "b_fagussylvatica", ["1f_summer"]) + variants(P, "b_quercusrobur", ["1f"])
    + variants(BC, "b_crataeguslaevigata", ["2s"]) + variants(BB, "b_corylusheterophylla", ["1s_summer"])
    + variants(P, "b_betulapendula", ["1f"]),
    "dry": variants(BB, "b_rosacanina", ["2s_summer"]) + variants(BB, "b_prunusspinosa", ["2s_summer"])
    + variants(BC, "b_crataeguslaevigata", ["1s", "2s"]) + variants(P, "b_quercusrobur", ["1f"]),
    "open": variants(BB, "b_rosacanina", ["1s_summer", "2s_summer"]) + variants(BB, "b_prunusspinosa", ["1s_summer"])
    + variants(BC, "b_crataeguslaevigata", ["2s"]) + variants(BB, "b_sambucusnigra", ["2s_summer"]),
}
DEAD = {
    "hardwood": variants(P, "d_fagussylvatica", ["fallen", "fallenb", "fallenc", "stump", "stumpb", "stumpc"])
    + variants(P, "d_quercusrobur", ["fallenb", "fallenc", "stump", "stumpb"])
    + variants(PB, "d_betulapendula", ["fallen", "stump"]),
    "conifer": variants(P, "d_piceaabies", ["fallen", "fallenb", "fallenc", "stump", "stumpb"])
    + variants(PB, "d_piceaabies", ["fallend", "fallene", "stumpc", "stumpd"]),
    "pine": variants(P, "d_pinussylvestris", ["fallen", "fallenb", "fallenc", "stump", "stumpb"]),
}
MIX = {
    "sprucefir": {"spruce": 0.72, "spruce_dead": 0.06, "birch": 0.12, "rowan": 0.05, "beech": 0.05},
    "northern": {"beech": 0.40, "birch": 0.25, "maple": 0.15, "spruce": 0.12, "rowan": 0.05, "ash": 0.03},
    "cove": {"ash": 0.18, "tulip": 0.12, "maple": 0.15, "beech": 0.15, "walnut": 0.08, "oak": 0.10,
             "ironwood": 0.05, "spruce": 0.12, "sycamore": 0.05},
    "oakpine": {"oak": 0.45, "pine": 0.30, "locust": 0.10, "birch": 0.05, "ironwood": 0.05, "maple": 0.05},
    "mixed": {"oak": 0.30, "maple": 0.15, "beech": 0.15, "birch": 0.10, "pine": 0.08, "locust": 0.07,
              "ash": 0.07, "spruce": 0.08},
    "open": {"apple": 0.18, "pear": 0.08, "plum": 0.04, "yard": 0.15, "oak": 0.15, "maple": 0.15, "walnut": 0.10,
             "sycamore": 0.15},
}
BUSH_FOR = {"sprucefir": "conifer", "northern": "conifer", "cove": "hardwood", "oakpine": "dry", "mixed": "hardwood",
            "open": "open"}
DEAD_FOR = {"sprucefir": "conifer", "northern": "hardwood", "cove": "hardwood", "oakpine": "pine", "mixed": "hardwood"}
ROAD_CLEAR = {"asf1": 6, "asf2": 4.5, "asf3": 3.5, "grav": 3, "mud": 2.5, "trail": 1.2}
WATER_CLEAR = {"river": 11, "stream": 6.5, "brook": 5.5, "seasonal": 1}   # past the water (tools/osm_water.py)


def blur(a, r):
    """Box blur of a 2D array with radius r cells (edges clamped)."""
    if r <= 0:
        return a
    out = a.astype(np.float64)
    for axis in (0, 1):
        pad = np.pad(out, [(r + 1, r) if k == axis else (0, 0) for k in range(2)], mode="edge")
        c = np.cumsum(pad, axis=axis)
        hi = np.take(c, np.arange(2 * r + 1, pad.shape[axis]), axis=axis)
        lo = np.take(c, np.arange(0, pad.shape[axis] - 2 * r - 1), axis=axis)
        out = (hi - lo) / (2 * r + 1)
    return out


def sample(grid, cellsize, xs, zs):
    """Bilinear sample of a south-origin grid at world x, z (arrays)."""
    fx, fz = xs / cellsize, zs / cellsize
    x0 = np.clip(fx.astype(int), 0, grid.shape[1] - 2)
    z0 = np.clip(fz.astype(int), 0, grid.shape[0] - 2)
    tx, tz = fx - x0, fz - z0
    return (grid[z0, x0] * (1 - tx) * (1 - tz) + grid[z0, x0 + 1] * tx * (1 - tz)
            + grid[z0 + 1, x0] * (1 - tx) * tz + grid[z0 + 1, x0 + 1] * tx * tz)


def main():
    elev_path, src, roads_path, water_path, rocks_path, out = sys.argv[1:7]
    footprints = json.load(open(sys.argv[7])) if len(sys.argv) > 7 else []   # tools/buildings.py
    os.makedirs(out, exist_ok=True)
    rng = random.Random(2812533524 + 2)
    nprng = np.random.default_rng(2812533524 + 2)
    elev = np.load(elev_path).astype(np.float64)

    # Fields on the 8 m grid, north up (row 0 = north), at cell centres.
    xs = (np.arange(N) + 0.5) * CELL
    zs = SIZE - (np.arange(N) + 0.5) * CELL
    gx, gz = np.meshgrid(xs, zs)
    h = sample(elev, 5.0, gx, gz)
    hs = blur(h, 5)
    dz_, dx_ = np.gradient(h, CELL)            # rows go south: d/drow = -d/dz
    slope = np.hypot(dx_, dz_)
    curv = blur(h, 12) - hs                    # > 0: hollow (cove), < 0: ridge
    up_z = -dz_                                # dh/dz (north)
    face = np.stack([-dx_, -up_z])             # downhill direction (east, north)
    norm = np.hypot(*face) + 1e-9
    southwest = (face[0] * -0.7071 + face[1] * -0.7071) / norm

    sat = np.asarray(Image.open(os.path.join(src, "satellite.png")).convert("RGB")
                     .resize((N, N), Image.BOX)).astype(np.float64)
    lum = blur(sat.mean(-1), 2)
    green = blur(sat[..., 1] - (sat[..., 0] + sat[..., 2]) / 2, 3)
    mask = np.asarray(Image.open(os.path.join(src, "mask.png")).convert("RGB"))
    grass = (mask[..., 0] == 120) & (mask[..., 1] == 200) & (mask[..., 2] == 60)
    grass = np.asarray(Image.fromarray((grass * 255).astype(np.uint8)).resize((N, N), Image.BOX)) / 255.0
    del mask

    water_lines = json.load(open(water_path))
    creek = Image.new("L", (N, N), 0)
    dc = ImageDraw.Draw(creek)
    for ln in water_lines:
        if ln["class"] in ("river", "stream", "brook"):
            dc.line([(x / CELL, (SIZE - z) / CELL) for x, z in ln["points"]], fill=255, width=int(120 / CELL))
    creek = np.asarray(creek) > 0

    zone = np.full((N, N), ZONES.index("mixed"), np.uint8)
    low = hs <= 1250
    sprucefir = (hs > 1680) | ((hs > 1480) & (green > 3.5))
    northern = ~sprucefir & ~low
    cove = low & ((curv > 2.0) | creek)
    oakpine = low & ~cove & ((curv < -2.0) | ((southwest > 0.35) & (slope > 0.35)))
    zone[northern] = ZONES.index("northern")
    zone[cove] = ZONES.index("cove")
    zone[oakpine] = ZONES.index("oakpine")
    zone[sprucefir] = ZONES.index("sprucefir")
    # The original map's grass covers Gatlinburg's whole wooded north end; only its
    # bright parts (lawns, lots, fields) are open. The rest grows as residential woods.
    # Bright steep ground is sun-lit or regrowing (the 2016 Chimney Tops fire) forest
    # in leaf-off imagery, not fields: open ground must also be fairly flat.
    town = grass > 0.5
    openland = ((lum > 105) & (slope < 0.3)) | (town & (lum > 92) & (slope < 0.45))
    zone[openland] = ZONES.index("open")
    evergreen = low & (green > 3.0) & ~openland
    np.save(os.path.join(out, "zones.npy"), zone)

    # Keep-clear maps at 2 m: one for trees, one (tighter) for bushes.
    n2 = int(SIZE / CLEAR_RES)
    keep_tree, keep_bush = Image.new("1", (n2, n2), 0), Image.new("1", (n2, n2), 0)
    dt, db = ImageDraw.Draw(keep_tree), ImageDraw.Draw(keep_bush)

    def line(d, points, half):
        px = [(x / CLEAR_RES, (SIZE - z) / CLEAR_RES) for x, z in points]
        d.line(px, fill=1, width=max(1, int(round(2 * half / CLEAR_RES))), joint="curve")
        # a disc on every point: PIL's wide line leaves pixel cracks at its joints (trees
        # grew in them, on the road), and round ends keep a road's end clear too
        r = half / CLEAR_RES
        for cx, cz in px:
            d.ellipse([cx - r, cz - r, cx + r, cz + r], fill=1)
    for ln in json.load(open(roads_path)):
        line(dt, ln["points"], ROAD_CLEAR[ln["family"]] + 1.5)
        line(db, ln["points"], ROAD_CLEAR[ln["family"]] + 0.5)
    # and the roads as built (tools/road_build.py), end caps and junction ends included
    built = os.path.join(os.path.dirname(roads_path), "centerlines.json")
    if os.path.isfile(built):
        for ln in json.load(open(built)):
            pts = [(p[0], p[1]) for p in ln["points"]]
            line(dt, pts, ROAD_CLEAR[ln["family"]] + 3.0)    # the 2 m raster loses up to a metre
            line(db, pts, ROAD_CLEAR[ln["family"]] + 2.0)
    for ln in water_lines:
        line(dt, ln["points"], WATER_CLEAR[ln["class"]] + 1.0)
        line(db, ln["points"], WATER_CLEAR[ln["class"]])
    rock_box = {}
    for raw in open(rocks_path):
        p = raw.strip().rstrip(";").split(";")
        name = p[0].strip('"')
        if name not in rock_box:
            for folder in (r"P:\DZ\rocks", r"P:\DZ\rocks_bliss"):
                f = os.path.join(folder, name + ".p3d")
                if os.path.isfile(f):
                    i = odol_info(f)
                    rock_box[name] = max(i["max"][0] - i["min"][0], i["max"][2] - i["min"][2]) / 2
        x, z, scale = float(p[1]) - EASTING, float(p[2]), float(p[6])
        r = rock_box[name] * scale * 0.85 / CLEAR_RES
        c, rr = x / CLEAR_RES, (SIZE - z) / CLEAR_RES
        dt.ellipse([c - r, rr - r, c + r, rr + r], fill=1)
        db.ellipse([c - r * 0.8, rr - r * 0.8, c + r * 0.8, rr + r * 0.8], fill=1)
    for fp in footprints:                        # building sites: no trees within 4 m, no bushes within 1.5 m
        c = np.mean(fp["corners"], axis=0)
        for d, grow in ((dt, 4.0), (db, 1.5)):
            grown = [c + (np.array(p) - c) * (1 + grow / max(1.0, np.hypot(*(np.array(p) - c)))) for p in fp["corners"]]
            d.polygon([(x / CLEAR_RES, (SIZE - z) / CLEAR_RES) for x, z in grown], fill=1)
    keep_tree, keep_bush = np.asarray(keep_tree), np.asarray(keep_bush)

    info = {}

    def model(path):
        if path not in info:
            i = odol_info(path)
            if i is None:
                raise SystemExit("not a binarized model: %s" % path)
            info[path] = (os.path.splitext(os.path.basename(path))[0], i["center"][1])
        return info[path]
    for group in (SPECIES, BUSHES, DEAD):
        for paths in group.values():
            for f in paths:
                model(f)

    def pick(weights):
        r, acc = rng.random() * sum(weights.values()), 0.0
        for k, w in weights.items():
            acc += w
            if r <= acc:
                return k
        return k

    files = {k: open(os.path.join(out, "tb_%s.txt" % k), "w", newline="\n") for k in ("trees", "bushes", "deadwood")}
    counts = {"trees": 0, "bushes": 0, "deadwood": 0}
    species_n = {}
    zone_cells = np.bincount(zone.ravel(), minlength=len(ZONES))

    def emit(kind, path, x, z, s_here, scale, sink):
        name, bcy = model(path)
        rel = bcy * scale - sink - min(s_here, 1.0) * 0.4 * scale
        files[kind].write('"%s";%.2f;%.2f;%.1f;0.000;0.000;%.3f;%.3f;\n'
                          % (name, x + EASTING, z, rng.uniform(0, 360), scale, rel))
        counts[kind] += 1

    for row in range(N):
        zr, sr = zone[row], slope[row]
        r_tree, r_bush, r_dead = (nprng.random(N) for _ in range(3))
        for col in range(N):
            zn = ZONES[zr[col]]
            pt, pb, pd = (v * DENSITY for v in RATES[zn])
            s_here = sr[col]
            if s_here > 1.0:
                pt *= 0.15
            elif s_here > 0.75:
                pt *= 0.6
            if zn != "open" and town[row, col]:
                pt *= 0.7
                pb *= 0.8
            if zn != "open" and creek[row, col]:
                pb += 0.2
            if evergreen[row, col]:
                pb += 0.2
            x0, z0 = col * CELL, SIZE - (row + 1) * CELL
            if r_tree[col] < pt:
                x, z = x0 + rng.uniform(0.5, CELL - 0.5), z0 + rng.uniform(0.5, CELL - 0.5)
                if not keep_tree[int((SIZE - z) / CLEAR_RES), int(x / CLEAR_RES)]:
                    mix = dict(MIX[zn])
                    if zn in ("cove", "mixed") and (evergreen[row, col] or creek[row, col]):
                        mix["spruce"] = mix.get("spruce", 0) + 0.25          # hemlock
                        if creek[row, col]:
                            mix["willow"] = mix.get("willow", 0) + 0.03
                    sp = pick(mix)
                    path = rng.choice(SPECIES[sp])
                    scale = rng.uniform(0.95, 1.25) if zn == "cove" else rng.uniform(0.85, 1.15)
                    emit("trees", path, x, z, s_here, scale, 0.25)
                    species_n[sp] = species_n.get(sp, 0) + 1
            if r_bush[col] < pb:
                x, z = x0 + rng.uniform(0, CELL), z0 + rng.uniform(0, CELL)
                if not keep_bush[int((SIZE - z) / CLEAR_RES), int(x / CLEAR_RES)]:
                    kind = "thicket" if (evergreen[row, col] or (creek[row, col] and zn != "open")) else BUSH_FOR[zn]
                    emit("bushes", rng.choice(BUSHES[kind]), x, z, s_here, rng.uniform(0.8, 1.3), 0.1)
            if zn != "open" and r_dead[col] < pd:
                x, z = x0 + rng.uniform(0, CELL), z0 + rng.uniform(0, CELL)
                if not keep_tree[int((SIZE - z) / CLEAR_RES), int(x / CLEAR_RES)]:
                    emit("deadwood", rng.choice(DEAD[DEAD_FOR[zn]]), x, z, s_here, rng.uniform(0.85, 1.15), 0.15)
        if row % 256 == 0:
            print("row %d / %d  trees %d" % (row, N, counts["trees"]), flush=True)
    for fh in files.values():
        fh.close()

    area = (CELL * CELL) / 10000.0
    with open(os.path.join(out, "summary.txt"), "w", newline="\n") as fh:
        fh.write("Forest grown from terrain, imagery and the mask (density x%.2f).\n\n" % DENSITY)
        fh.write("zones (share of the map, forest floor surface):\n")
        for k, name in enumerate(ZONES):
            fh.write("  %-10s %5.1f%%  %s\n" % (name, 100.0 * zone_cells[k] / zone.size, ZONE_SURFACE.get(name, "(kept)")))
        fh.write("\nobjects:\n")
        for k in ("trees", "bushes", "deadwood"):
            fh.write("  %-9s %9d  (%.0f per hectare)\n" % (k, counts[k], counts[k] / (zone.size * area)))
        fh.write("  %-9s %9d\n\ntrees by species (DayZ model family standing in):\n" % ("total", sum(counts.values())))
        stand_in = {"spruce": "red spruce, Fraser fir, hemlock (t_piceaabies)", "spruce_dead": "dead Fraser fir",
                    "beech": "American beech (t_fagussylvatica)", "birch": "yellow birch (t_betulapendula)",
                    "maple": "sugar/red maple (t_acer)", "rowan": "mountain ash (t_sorbus)",
                    "oak": "red/chestnut oak (t_quercusrobur)", "pine": "pitch/Virginia pine (t_pinussylvestris)",
                    "ash": "ash, tulip poplar (t_fraxinusexcelsior)", "tulip": "tulip poplar (t_populusnigra)",
                    "sycamore": "sycamore (t_populusalba)", "walnut": "black walnut (t_juglansregia)",
                    "ironwood": "ironwood (t_carpinus)", "locust": "black locust (t_robiniapseudoacacia)",
                    "willow": "black willow (t_salixalba)", "apple": "apple", "pear": "pear", "plum": "plum",
                    "yard": "yard trees (t_town)"}
        for sp, n in sorted(species_n.items(), key=lambda kv: -kv[1]):
            fh.write("  %-9s %9d  %s\n" % (sp, n, stand_in.get(sp, "")))
    print(open(os.path.join(out, "summary.txt")).read())


if __name__ == "__main__":
    main()
