"""Pick the main menu's camera spots (cfgCharacterScenes >> greatsmokymountains) and
write them into config.cpp.

    python tools/scenes.py source/buildings/elevation.npy config.cpp

DayZ's intro scene (scripts\\5_Mission\\dayzintroscene.c) picks one of the world's
cfgCharacterScenes at random, puts the camera on the ground at `position`
(x, z; the height is ignored), looks at `target` (x, z, height above sea level)
and stands the character 3.7 m in front of it. Each spot here is an overlook,
a gap or a bald summit from config.cpp's names (or a street in town), moved to
the nearest flat ground that is clear of trees, bushes, rocks, buildings and
water for the camera and the character, and aimed at the named peak it can see
best: nothing in the way, neither terrain nor tree tops (each tree's top taken
as twice its base offset above the ground). Date, time and weather vary by spot.
It replaces only the class cfgCharacterScenes block, so it can be rerun.
"""

import math
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import bilinear  # noqa: E402
from mission import read_tb, SIZE, SRC  # noqa: E402

WORLD = "greatsmokymountains"
EYE = 1.7
CELL = 4.0                      # tree-top and obstacle grid (m)
CAM_CLEAR, CHAR_CLEAR = 2.5, 2.0
CHAR_AHEAD = 3.7
MAX_SLOPE = 0.25                # rise over run at the camera and the character
SEARCH = 120.0                  # how far a spot may move from its named place
BUSH_TOP = 3.0

# (name in config.cpp, or "x,z" with a label; date (y, m, d, h, min), overcast, fog)
SPOTS = [
    ("Newfound Gap", (1985, 10, 18, 16, 40), 0.25, 0.05),
    ("Ben Morton Overlook", (1985, 10, 20, 8, 10), 0.3, 0.12),
    ("Luftee Overlook", (1985, 6, 14, 18, 20), 0.15, 0.02),
    ("Chimney point", (1985, 10, 12, 10, 30), 0.35, 0.04),
    ("Inspiration Point", (1985, 5, 30, 7, 20), 0.2, 0.15),
    ("Deep Creek Valley Overlook #1", (1985, 10, 25, 15, 10), 0.4, 0.06),
    ("Charles A Webb Overlook", (1985, 7, 9, 11, 45), 0.2, 0.03),
    ("Myrtle Point", (1985, 9, 28, 7, 5), 0.1, 0.1),
    ("Cliff Top", (1985, 10, 5, 17, 50), 0.2, 0.04),
    ("Gatlinburg", (1985, 10, 22, 9, 15), 0.45, 0.05),
    ("Sugarlands", (1985, 4, 26, 13, 0), 0.5, 0.03),
    ("LeConte Lodge", (1985, 10, 9, 18, 5), 0.2, 0.08),
    ("Twin Creeks", (1985, 10, 15, 12, 20), 0.35, 0.02),
    ("Cartertown", (1985, 6, 2, 9, 40), 0.3, 0.06),
    ("Glade", (1985, 10, 28, 16, 0), 0.4, 0.03),
    ("Pinnacle", (1985, 9, 12, 8, 30), 0.25, 0.1),
    ("Zion Grove", (1985, 5, 19, 17, 30), 0.2, 0.04),
    ("Pittman Center", (1985, 10, 3, 11, 10), 0.45, 0.02),
    ("Greenbrier Quarters & Ranger Station", (1985, 4, 12, 14, 30), 0.5, 0.05),
]


def config_places(text):
    out = {}
    for m in re.finditer(r'name="([^"]+)";\s*position\[\]=\{([-\d.]+),([-\d.]+)\};\s*type="(\w+)"', text):
        out[m.group(1)] = (float(m.group(2)), float(m.group(3)), m.group(4))
    return out


class World:
    def __init__(self, elev):
        self.elev = elev
        self.cell = SIZE / elev.shape[0]
        gz, gx = np.gradient(elev.astype(np.float32), self.cell)
        self.slope = np.hypot(gx, gz)
        n = int(SIZE / CELL)
        self.top = np.zeros((n, n), np.float32)        # highest tree/bush top above sea level
        self.block = np.zeros((n, n), bool)             # anything a camera or character can't stand in
        codes = {}
        for f, kind in (("forest/tb_trees.txt", "tree"), ("forest/tb_bushes.txt", "bush"),
                        ("forest/tb_deadwood.txt", "dead"), ("rocks/tb_rocks.txt", "rock"),
                        ("water/tb_water.txt", "water"), ("buildings/tb_buildings.txt", "building"),
                        ("buildings/tb_cabins.txt", "building"), ("buildings/tb_fuel.txt", "building"),
                        ("buildings/tb_fences.txt", "fence"), ("buildings/tb_bridges.txt", "building"),
                        ("buildings/tb_skybridge.txt", "building")):
            _, rows = read_tb(os.path.join(SRC, f), codes)
            x, z, scale, rel = rows[:, 0], rows[:, 1], rows[:, 5], rows[:, 6]
            g = self.h_many(x, z)
            i = np.clip((z / CELL).astype(int), 0, n - 1)
            j = np.clip((x / CELL).astype(int), 0, n - 1)
            if kind in ("tree", "bush"):
                top = g + (2.0 * rel if kind == "tree" else np.minimum(2.0 * rel, BUSH_TOP))
                np.maximum.at(self.top, (i, j), top.astype(np.float32))
            reach = {"tree": 0, "bush": 0, "dead": 1, "rock": 2, "water": 3, "building": 4, "fence": 1}[kind]
            for di in range(-reach, reach + 1):
                for dj in range(-reach, reach + 1):
                    self.block[np.clip(i + di, 0, n - 1), np.clip(j + dj, 0, n - 1)] = True
            print("  %-28s %8d" % (f, len(rows)), flush=True)

    def h(self, x, z):
        return bilinear(self.elev, x / self.cell, z / self.cell)

    def h_many(self, x, z):
        gx, gz = x / self.cell, z / self.cell
        x0 = np.clip(np.floor(gx).astype(int), 0, self.elev.shape[1] - 2)
        z0 = np.clip(np.floor(gz).astype(int), 0, self.elev.shape[0] - 2)
        fx, fz = gx - x0, gz - z0
        e = self.elev
        return (e[z0, x0] * (1 - fx) * (1 - fz) + e[z0, x0 + 1] * fx * (1 - fz)
                + e[z0 + 1, x0] * (1 - fx) * fz + e[z0 + 1, x0 + 1] * fx * fz)

    def clear(self, x, z, r):
        k = int(math.ceil(r / CELL))
        i, j = int(z / CELL), int(x / CELL)
        if i - k < 0 or j - k < 0 or i + k >= self.block.shape[0] or j + k >= self.block.shape[1]:
            return False
        if self.block[i - k:i + k + 1, j - k:j + k + 1].any():
            return False
        kk = max(1, int(math.ceil(r / self.cell)))
        ei, ej = int(z / self.cell), int(x / self.cell)
        return float(self.slope[ei - kk:ei + kk + 1, ej - kk:ej + kk + 1].max()) <= MAX_SLOPE

    def sight(self, x, z, tx, tz, th):
        """Lowest clearance (m) of the sight line from the eye at (x, z) to (tx, tz, th) over
        terrain and tree tops, skipping the character's few metres; negative = blocked."""
        h0 = self.h(x, z) + EYE
        d = math.hypot(tx - x, tz - z)
        s = np.arange(6.0, d - 30.0, 2.0)
        if not len(s):
            return 99.0
        px, pz = x + (tx - x) * s / d, z + (tz - z) * s / d
        line = h0 + (th - h0) * s / d
        ground = self.h_many(px, pz)
        i = np.clip((pz / CELL).astype(int), 0, self.top.shape[0] - 1)
        j = np.clip((px / CELL).astype(int), 0, self.top.shape[1] - 1)
        obstacle = np.maximum(ground, self.top[i, j])
        return float((line - obstacle).min())


def best_target(w, x, z, peaks):
    """The named peak that stands highest in view (angle above the horizontal) with a
    clear line, or else the farthest clear point downhill."""
    h0 = w.h(x, z) + EYE
    best = None
    for name, (px, pz) in peaks.items():
        d = math.hypot(px - x, pz - z)
        if d < 400 or d > 12000:
            continue
        top = w.h(px, pz)
        if w.sight(x, z, px, pz, top) < 1.0:
            continue
        score = math.atan2(top - h0, d) + 0.02 * min(d, 8000) / 8000
        if best is None or score > best[0]:
            best = (score, name, px, pz, top)
    if best:
        return best[1:]
    for d in (3000.0, 2000.0, 1200.0, 700.0):
        cands = []
        for a in range(0, 360, 10):
            t = math.radians(a)
            px, pz = x + d * math.sin(t), z + d * math.cos(t)
            if 0 < px < SIZE and 0 < pz < SIZE:
                ph = w.h(px, pz)
                if w.sight(x, z, px, pz, ph) >= 1.0:
                    cands.append((ph, px, pz))
        if cands:
            ph, px, pz = min(cands)
            return "view %.0f m out" % d, px, pz, ph
    return None


def place(w, x, z, peaks):
    """Nearest clear flat spot to (x, z) with its target and the character's spot also clear."""
    for d in np.arange(0.0, SEARCH + 0.1, 2.0):
        steps = 1 if d == 0 else int(2 * math.pi * d / 2.0)
        for k in range(steps):
            a = 2 * math.pi * k / steps
            cx, cz = x + d * math.cos(a), z + d * math.sin(a)
            if not w.clear(cx, cz, CAM_CLEAR):
                continue
            t = best_target(w, cx, cz, peaks)
            if not t:
                continue
            name, tx, tz, th = t
            dd = math.hypot(tx - cx, tz - cz)
            ux, uz = (tx - cx) / dd, (tz - cz) / dd
            chx, chz = cx + ux * CHAR_AHEAD + uz * 0.7, cz + uz * CHAR_AHEAD - ux * 0.7
            if w.clear(chx, chz, CHAR_CLEAR):
                return cx, cz, name, tx, tz, th
    return None


def block(scenes, nl):
    t = "\t"
    out = ["class cfgCharacterScenes", "{", t + "class " + WORLD, t + "{"]
    for k, s in enumerate(scenes, 1):
        out += [t * 2 + "class loc%d" % k, t * 2 + "{",
                t * 3 + "// %s, looking at %s" % (s["label"], s["target_name"]),
                t * 3 + "target[]={%.1f,%.1f,%.1f};" % s["target"],
                t * 3 + "position[]={%.1f,%.1f,1};" % s["position"],
                t * 3 + "fov=0.5236;",
                t * 3 + "date[]={%d,%d,%d,%d,%d};" % s["date"],
                t * 3 + "overcast=%g;" % s["overcast"],
                t * 3 + "rain=0;",
                t * 3 + "fog=%g;" % s["fog"],
                t * 2 + "};"]
    out += [t + "};", "};"]
    return nl.join(out)


def main():
    elev_path, config = sys.argv[1:3]
    text = open(config, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in text else "\n"
    places = config_places(text)
    peaks = {n: (p[0], p[1]) for n, p in places.items() if p[2] == "Hill"}
    print("reading objects")
    w = World(np.load(elev_path))
    scenes = []
    for label, date, overcast, fog in SPOTS:
        x, z, _ = places[label]
        got = place(w, x, z, peaks)
        if not got:
            print("  %-30s no clear spot within %.0f m: left out" % (label, SEARCH))
            continue
        cx, cz, tname, tx, tz, th = got
        scenes.append({"label": label, "target_name": tname, "target": (tx, tz, th), "position": (cx, cz),
                       "date": date, "overcast": overcast, "fog": fog})
        print("  %-30s at %7.1f %7.1f (%4.0f m off, ground %6.1f) -> %-22s %5.0f m away, clearance %.1f m"
              % (label, cx, cz, math.hypot(cx - x, cz - z), w.h(cx, cz), tname,
                 math.hypot(tx - cx, tz - cz), w.sight(cx, cz, tx, tz, th)))
    new = block(scenes, nl)
    pat = re.compile(r"^class cfgCharacterScenes\r?\n\{.*?^\};", re.S | re.M)
    if pat.search(text):
        text = pat.sub(lambda m: new, text, count=1)
    else:
        i = text.index("class CfgWorlds")
        text = text[:i] + new + nl + text[i:]
    open(config, "w", encoding="utf-8", newline="").write(text)
    print("%d scenes written to %s" % (len(scenes), config))


if __name__ == "__main__":
    main()
