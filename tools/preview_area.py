"""Draw one area of the map: shaded terrain with water, rocks, roads and trails on top.

    python tools/preview_area.py <elevation .npy> <centre x> <centre z> <half size m> <out.png> <tb_*.txt ...>

Water pieces are blue, cliff faces red, outcrops orange, boulders grey, road
parts white, trail parts yellow, conifers dark green, hardwoods green, bushes
pale green, deadwood brown, buildings magenta, fences and guardrails cyan and
bridges orange, each drawn at its position.
"""

import math
import sys

import numpy as np
from PIL import Image, ImageDraw

EASTING = 200000.0
PX = 2                           # pixels per metre... per 1 m? see SCALE below
SCALE = 1.0                      # pixels per metre


BUILDING = ("house_", "hotel", "tenement", "houseblock", "office", "city_", "village_", "church", "chapel", "shed_",
            "garage", "barn", "farm_", "workshop", "factory", "fuelstation", "repair_center")


def colour(name):
    if name.startswith("bridge_"):
        return (255, 120, 0)
    if name.startswith(("wall_", "misc_crashbarrier")):
        return (0, 230, 230)
    if name.startswith(BUILDING):
        return (230, 40, 200)
    if name.startswith("t_piceaabies") or name.startswith("t_pinus"):
        return (20, 90, 40)
    if name.startswith("t_"):
        return (90, 170, 60)
    if name.startswith("b_"):
        return (170, 200, 90)
    if name.startswith("d_"):
        return (130, 90, 50)
    if name.startswith(("stream_", "river_", "pond_")):
        return (60, 150, 255)
    if name.startswith(("rock_wall", "rock_monolith1", "rock_monolith2")):
        return (230, 40, 40)
    if name.startswith("rock_"):
        return (255, 150, 30)
    if name.startswith(("stone", "stones_")):
        return (170, 170, 170)
    if name.startswith("path_"):
        return (255, 230, 0)
    return (255, 255, 255)


def main():
    elev = np.load(sys.argv[1]).astype(np.float64)
    cx, cz, half = (float(v) for v in sys.argv[2:5])
    out = sys.argv[5]
    cell = 5.0
    i0, i1 = int((cx - half) / cell), int((cx + half) / cell)
    j0, j1 = int((cz - half) / cell), int((cz + half) / cell)
    e = elev[j0:j1, i0:i1][::-1]                     # north up
    gy, gx = np.gradient(e, cell)
    shade = np.clip(0.55 + (-gx * 0.6 - gy * 0.6) / np.sqrt(1 + gx * gx + gy * gy), 0, 1)
    size = int(2 * half * SCALE)
    img = Image.fromarray((shade * 200 + 30).astype(np.uint8)).resize((size, size), Image.BILINEAR).convert("RGB")
    d = ImageDraw.Draw(img)

    def px(x, z):
        return ((x - (cx - half)) * SCALE, ((cz + half) - z) * SCALE)
    from build_world import read_layers_cfg  # noqa: F401  (keeps tools importable together)
    for path in sys.argv[6:]:
        for line in open(path):
            p = line.strip().rstrip(";").split(";")
            if len(p) < 8:
                continue
            name = p[0].strip('"')
            x, z, yaw, scale = float(p[1]) - EASTING, float(p[2]), float(p[3]), float(p[6])
            if abs(x - cx) > half or abs(z - cz) > half:
                continue
            r = 1.5 * scale if name.startswith(("stone", "path_", "b_", "d_", "wall_", "misc_")) else (
                2.2 * scale if name.startswith("t_") else 6 * scale if name.startswith(BUILDING + ("bridge_",)) else 3 * scale)
            if name.startswith(("stream_", "river_", "asf", "grav", "mud", "path_", "rock_wall")):
                length = {"stream_14_24": 24, "stream_14_12": 12, "stream_14_6": 6, "river_24_24": 24,
                          "river_24_12": 12, "river_24_6": 6}.get(name, 10 if name.startswith("path_") else 12.5)
                if name.startswith("rock_wall"):
                    length = 60
                dx, dz = math.sin(math.radians(yaw)) * length * scale / 2, math.cos(math.radians(yaw)) * length * scale / 2
                w = max(1, int((8 if name.startswith(("stream", "river", "rock_wall")) else 4) * scale * SCALE))
                d.line([px(x - dx, z - dz), px(x + dx, z + dz)], fill=colour(name), width=w)
            else:
                a, b = px(x, z)
                d.ellipse([a - r, b - r, a + r, b + r], fill=colour(name))
    img.save(out)


if __name__ == "__main__":
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    main()
