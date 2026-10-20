"""Place rocks, outcrops and cliff faces where the terrain says they belong.

    python tools/rocks.py <elevation .npy> source/roads/lines.json source/water/lines.json
        source/water/osm_rocks.json tools/georef.json source/rocks

OpenStreetMap barely maps rock in the park, so this reads the ground itself,
block by 30 x 30 m block:
  steepest slope over 45 degrees     a cliff face (rock_wallh1-6 / rock_wallv / rock_monolith),
                                     its long side along the contour, set into the slope
  37 to 45 degrees                   an outcrop (rock_monolith / rock_spike / rock_apart), some blocks
  mean slope over 27 degrees         scattered boulders (stone1-10, mossy stone6-10_moss)
  within 25 m of a creek             more boulders: the Smokies' boulder-choked streams
plus an outcrop at each mapped cliff and on the named rocky ridges (Anakeesta,
the Boulevard, Rocky Spur, Chimney Tops). Nothing goes within reach of a road,
a trail or a creek channel.

Writes tb_rocks.txt (Terrain Builder object import, height relative to the
ground) and summary.txt.
"""

import json
import math
import os
import random
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import bilinear  # noqa: E402
from geo import utm  # noqa: E402

EASTING = 200000.0
SIZE = 20480
CELL = 5.0
BLOCK = 30.0
CLEAR_RES = 2.0                  # metres per pixel of the keep-clear map

WALLS = ["rock_wallh1", "rock_wallh2", "rock_wallh3", "rock_wallh4", "rock_wallh5", "rock_wallh6", "rock_wallv",
         "rock_monolith1", "rock_monolith2"]
OUTCROPS = ["rock_monolith3", "rock_monolith4", "rock_spike1", "rock_spike2", "rock_spike3", "rock_apart1", "rock_apart2"]
BOULDERS = ["stone1", "stone2", "stone3", "stone4", "stone5", "stone6", "stone7", "stone8", "stone9", "stone10",
            "stone6_moss", "stone7_moss", "stone8_moss", "stone9_moss", "stone10_moss"]
WALL_SLOPE, OUTCROP_SLOPE, BOULDER_SLOPE = 1.0, 0.75, 0.5
BOULDER_RATE = 0.12              # boulders per block on steep ground
CREEK_RATE = 0.45                # extra boulders per block within CREEK_NEAR of a creek
CREEK_NEAR = 25.0
ROCKY_RIDGES = ("Anakeesta Ridge", "The Boulevard", "Rocky Spur", "Rocky Fork Ridge", "Greenbrier Pinnacle")
ROCKY_PEAKS = ("Chimney Tops", "Anakeesta Knob", "Peregrine Peak", "Lookout Rock", "Cliff Top", "Myrtle Point")
# Clearances (metres from the centre line) for things that must stay free of rock.
ROAD_CLEAR = {"asf1": 9, "asf2": 7.5, "asf3": 6.5, "grav": 6, "mud": 5, "trail": 3}
WATER_CLEAR = {"river": 12, "stream": 7, "brook": 6, "seasonal": 2}   # past the water (tools/osm_water.py)


def model_box(path):
    """(width, height, length) of a binarized model, from its header."""
    d = open(path, "rb").read(256)
    n = struct.unpack_from("<i", d, 8)[0]
    b = 12 + 4 * n + 24 + 12 + 12
    mn = struct.unpack_from("<3f", d, b)
    mx = struct.unpack_from("<3f", d, b + 12)
    return mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]


def find(name):
    for folder in (r"P:\DZ\rocks", r"P:\DZ\rocks_bliss"):
        p = os.path.join(folder, name + ".p3d")
        if os.path.isfile(p):
            return p
    raise SystemExit("no model %s under P:\\DZ\\rocks or rocks_bliss" % name)


def main():
    elev_path, roads_path, water_path, osm_rocks_path, georef_path, out = sys.argv[1:7]
    footprints = json.load(open(sys.argv[7])) if len(sys.argv) > 7 else []   # tools/buildings.py
    os.makedirs(out, exist_ok=True)
    rng = random.Random(2812533524 + 1)
    elev = np.load(elev_path).astype(np.float64)
    gz, gx = np.gradient(elev, CELL)
    slope = np.hypot(gx, gz)
    boxes = {n: model_box(find(n)) for n in WALLS + OUTCROPS + BOULDERS}

    # Keep-clear map at 2 m: roads, trails, creek channels.
    n = int(SIZE / CLEAR_RES)
    clear = Image.new("1", (n, n), 0)
    draw = ImageDraw.Draw(clear)

    def line(points, half):
        draw.line([(x / CLEAR_RES, (SIZE - z) / CLEAR_RES) for x, z in points], fill=1,
                  width=max(1, int(round(2 * half / CLEAR_RES))), joint="curve")
    roads = json.load(open(roads_path))
    for ln in roads:
        line(ln["points"], ROAD_CLEAR[ln["family"]])
    water = json.load(open(water_path))
    for ln in water:
        line(ln["points"], WATER_CLEAR[ln["class"]])
    for fp in footprints:                        # building sites and their levelled pads (13 m round them):
        c = np.mean(fp["corners"], axis=0)       # a pad's cut bank isn't a cliff
        grown = [c + (np.array(p) - c) * (1 + 13.0 / max(1.0, np.hypot(*(np.array(p) - c)))) for p in fp["corners"]]
        draw.polygon([(x / CLEAR_RES, (SIZE - z) / CLEAR_RES) for x, z in grown], fill=1)
    clear = np.asarray(clear)

    near = Image.new("1", (n, n), 0)
    dn = ImageDraw.Draw(near)
    for ln in water:
        if ln["class"] in ("river", "stream", "brook"):
            dn.line([(x / CLEAR_RES, (SIZE - z) / CLEAR_RES) for x, z in ln["points"]], fill=1,
                    width=int(2 * CREEK_NEAR / CLEAR_RES), joint="curve")
    near = np.asarray(near)

    def is_clear(x, z, radius):
        c0, c1 = int((x - radius) / CLEAR_RES), int((x + radius) / CLEAR_RES) + 1
        r0, r1 = int((SIZE - z - radius) / CLEAR_RES), int((SIZE - z + radius) / CLEAR_RES) + 1
        if c0 < 0 or r0 < 0 or c1 > n or r1 > n:
            return False
        return not clear[r0:r1, c0:c1].any()

    objects, counts = [], {}

    def place(name, x, z, yaw, scale, bury):
        """bury: fraction of the model's height below the ground on its uphill side."""
        w, h, l = (v * scale for v in boxes[name])
        i, j = x / CELL, z / CELL
        ground = bilinear(elev, i, j)
        s = bilinear(slope, i, j)
        # Centre height: sunk by `bury` of its height, and further on a slope so the
        # downhill side doesn't hang in the air.
        y = ground + h / 2 - bury * h - s * min(w, l) / 2
        objects.append((name, x, z, yaw % 360, scale, y - ground))
        counts[name] = counts.get(name, 0) + 1

    nb = int(SIZE / BLOCK)
    per = int(BLOCK / CELL)
    for bj in range(nb):
        for bi in range(nb):
            sl = slope[bj * per:(bj + 1) * per, bi * per:(bi + 1) * per]
            if sl.size == 0:
                continue
            k = int(sl.argmax())
            jj, ii = bj * per + k // sl.shape[1], bi * per + k % sl.shape[1]
            smax, smean = float(sl.max()), float(sl.mean())
            x0, z0 = bi * BLOCK, bj * BLOCK
            if smax > WALL_SLOPE:
                x, z = ii * CELL + rng.uniform(-2, 2), jj * CELL + rng.uniform(-2, 2)
                name = rng.choice(WALLS)
                scale = rng.uniform(0.3, 0.55) if name == "rock_wallv" else rng.uniform(0.45, 0.9)
                w, h, l = (v * scale for v in boxes[name])
                if is_clear(x, z, max(w, l) / 2):
                    aspect = math.degrees(math.atan2(-gx[jj, ii], -gz[jj, ii]))     # downhill
                    place(name, x, z, aspect + 90 + rng.uniform(-15, 15), scale, 0.45)
            elif smax > OUTCROP_SLOPE and rng.random() < 0.45:
                x, z = ii * CELL + rng.uniform(-3, 3), jj * CELL + rng.uniform(-3, 3)
                name = rng.choice(OUTCROPS)
                scale = rng.uniform(0.35, 0.8)
                w, h, l = (v * scale for v in boxes[name])
                if is_clear(x, z, max(w, l) / 2):
                    place(name, x, z, rng.uniform(0, 360), scale, 0.4)
            rate = (BOULDER_RATE if smean > BOULDER_SLOPE else 0.0)
            cr, cc = int((SIZE - z0 - BLOCK / 2) / CLEAR_RES), int((x0 + BLOCK / 2) / CLEAR_RES)
            if 0 <= cr < n and 0 <= cc < n and near[cr, cc]:
                rate += CREEK_RATE
            count = int(rate) + (1 if rng.random() < rate - int(rate) else 0)
            for _ in range(count):
                x, z = x0 + rng.uniform(0, BLOCK), z0 + rng.uniform(0, BLOCK)
                name = rng.choice(BOULDERS)
                scale = rng.uniform(0.5, 1.6)
                w, h, l = (v * scale for v in boxes[name])
                if is_clear(x, z, max(w, l) / 2):
                    place(name, x, z, rng.uniform(0, 360), scale, 0.3)

    # Mapped cliffs, rocky ridges and peaks.
    geo = json.load(open(georef_path))
    ox, oy = geo["offset_x"], geo["offset_y"]
    named = 0
    for e in json.load(open(osm_rocks_path, encoding="utf-8"))["elements"]:
        t = e.get("tags", {})
        nat, name = t.get("natural"), t.get("name", "")
        pts = []
        if e["type"] == "node" and (nat == "cliff" or (nat == "peak" and name in ROCKY_PEAKS)):
            pts = [utm(e["lat"], e["lon"], 17)]
        elif e["type"] == "way" and nat == "ridge" and name in ROCKY_RIDGES:
            geom = e.get("geometry", [])
            pts = [utm(p["lat"], p["lon"], 17) for p in geom[::max(1, len(geom) // 12)]]
        for ux, uy in pts:
            x, z = ux + ox, uy + oy
            if not (50 < x < SIZE - 50 and 50 < z < SIZE - 50):
                continue
            for _ in range(3):
                px, pz = x + rng.uniform(-15, 15), z + rng.uniform(-15, 15)
                rock = rng.choice(OUTCROPS)
                scale = rng.uniform(0.4, 0.8)
                w, h, l = (v * scale for v in boxes[rock])
                if is_clear(px, pz, max(w, l) / 2):
                    place(rock, px, pz, rng.uniform(0, 360), scale, 0.35)
                    named += 1

    with open(os.path.join(out, "tb_rocks.txt"), "w", newline="\n") as fh:
        for name, x, z, yaw, scale, rel in objects:
            fh.write('"%s";%.3f;%.3f;%.3f;0.000;0.000;%.3f;%.3f;\n' % (name, x + EASTING, z, yaw, scale, rel))
    groups = {"cliff faces": WALLS, "outcrops": OUTCROPS, "boulders": BOULDERS}
    with open(os.path.join(out, "summary.txt"), "w", newline="\n") as fh:
        fh.write("Rocks placed from the terrain's slopes, plus mapped cliffs and rocky ridges/peaks\n")
        fh.write("(c) OpenStreetMap contributors, ODbL.\n\n")
        for g, names in groups.items():
            fh.write("%-12s %6d\n" % (g, sum(counts.get(m, 0) for m in names)))
        fh.write("%-12s %6d  (at mapped cliffs, rocky ridges and peaks, included above)\n" % ("named spots", named))
        fh.write("%-12s %6d\n\n" % ("total", len(objects)))
        for m in sorted(counts):
            fh.write("  %-16s %6d\n" % (m, counts[m]))
    print(open(os.path.join(out, "summary.txt")).read())


if __name__ == "__main__":
    main()
