"""Draw the in-game map's overlay (the "usermap"): hiking trails, creeks, rivers
and ponds, over the engine's own map, in the style of vanilla Chernarus's
(DZ\\gear\\navigation\\data\\usermap).

    python tools/usermap.py <ImageToPAA.exe> [<work folder>]

Writes data/usermap/s_XXX_YYY_lco.paa: 32 x 32 tiles of 512 px covering the
whole map evenly (640 m a tile, 1.25 m a pixel), XXX the column from the west
and YYY the row from the north (000 to 031), so pixel (0, 0) of s_000_000 is the
map's north-west corner. Tiles with nothing on them are 4 x 4 and fully
transparent, as vanilla's are. config.cpp points at the folder with
userMapPath="greatsmokymountains\\data\\usermap" (vanilla: "dz\\gear\\navigation\\data\\usermap").

The PNG tiles go to <work folder> (default source/usermap/tiles, never data/),
and a 2048 px view of the whole overlay over the satellite preview to
source/usermap/usermap_preview.png (there each 8 x 8 block shows its strongest
pixel, so 2 px creeks stay visible).

Drawn like vanilla's, in solid colours with hard edges: ImageToPAA makes _lco
tiles DXT1 with 1-bit alpha, the same format as the vanilla tiles.
  ponds (the 48 with water in game)    filled light blue 164,196,226
  rivers                               4 px light blue
  named creeks                         2.5 px light blue
  unnamed perennial creeks             2 px light blue
  named hiking and horse trails        4 px, round joins and ends: the Appalachian
                                       Trail red 193,0,0, the rest yellow 255,227,12,
                                       green 49,138,0 or blue 20,32,197 by the printed
                                       map's rule (trail_colour() in tools/topo_map.py)
  unnamed paths                        2 px muted brown 128,104,80
Seasonal creeks and ditches are left out (they have no water in game), and so
are the roads (the engine draws its own). Trails go over the water. Everything
is drawn at 4 x and reduced; a pixel is opaque where lines cover at least half
of it, so the hard edges still follow the lines smoothly, and where a trail
crosses a creek the edge pixels mix the two colours.

Sources: source/roads/lines.json (tools/osm_roads.py), source/water/lines.json
and source/water/osm_water.json (tools/osm_water.py), tools/georef.json.
"""

import concurrent.futures
import json
import math
import os
import subprocess
import sys
import zlib
from collections import defaultdict

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import utm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "source")
SIZE = 20480.0
TILES, TILE = 32, 512
PX = SIZE / (TILES * TILE)                   # 1.25 m per pixel
SS = 4                                       # drawn at 4 x, then reduced
PREVIEW = 2048

# Vanilla usermap palette.
WATER = (164, 196, 226)
RED, YELLOW, GREEN, BLUE = (193, 0, 0), (255, 227, 12), (49, 138, 0), (20, 32, 197)
TRAIL_COLOURS = [RED, YELLOW, GREEN, BLUE]
PATH = (128, 104, 80)
LAYERS = [WATER, PATH, YELLOW, GREEN, BLUE, RED]          # bottom to top
WATER_WIDTH = {"river": 4.0, "stream": 2.5, "brook": 2.0}  # px; "seasonal" left out
TRAIL_WIDTH, PATH_WIDTH = 4.0, 2.0
POND_WATER = ("pond", "lake", "reservoir", "basin")        # as tools/osm_water.py


def trail_colour(name):
    """The printed map's rule (tools/topo_map.py), in the usermap's palette."""
    if name == "Appalachian Trail":
        return RED
    return TRAIL_COLOURS[1 + zlib.crc32(name.encode()) % 3]


def to_px(pts):
    """Map metres (x east, z north) to overlay pixels (x east, y down from the north edge)."""
    p = np.asarray(pts, np.float64)
    return np.column_stack([p[:, 0] / PX, (SIZE - p[:, 1]) / PX])


def length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def load():
    """The shapes to draw: {colour: [(pixel points, line width in px, or None for a filled polygon)]}."""
    geo = json.load(open(os.path.join(ROOT, "tools", "georef.json")))
    shapes = {c: [] for c in LAYERS}
    stats = defaultdict(float)
    # Ponds: the same ones tools/osm_water.py fills with water.
    for e in json.load(open(os.path.join(SRC, "water", "osm_water.json"), encoding="utf-8"))["elements"]:
        t = e.get("tags", {})
        if e["type"] == "node" or "waterway" in t or t.get("natural") != "water" \
                or t.get("water", "pond") not in POND_WATER:
            continue
        geom = e.get("geometry") or [p for m in e.get("members", []) for p in (m.get("geometry") or [])]
        pts = []
        for g in geom:
            if g:
                x, z = utm(g["lat"], g["lon"], 17)
                pts.append((x + geo["offset_x"], z + geo["offset_y"]))
        if len(pts) >= 4 and all(0 <= x <= SIZE and 0 <= z <= SIZE for x, z in pts):
            shapes[WATER].append((to_px(pts), None))
            stats["ponds"] += 1
    for ln in json.load(open(os.path.join(SRC, "water", "lines.json"))):
        w = WATER_WIDTH.get(ln["class"])
        if w and len(ln["points"]) >= 2:
            shapes[WATER].append((to_px(ln["points"]), w))
            stats[ln["class"] + " km"] += length(ln["points"]) / 1000
    for ln in json.load(open(os.path.join(SRC, "roads", "lines.json"))):
        if ln["group"] != "trails" or len(ln["points"]) < 2:
            continue
        if ln["name"]:
            shapes[trail_colour(ln["name"])].append((to_px(ln["points"]), TRAIL_WIDTH))
            stats["named trail km"] += length(ln["points"]) / 1000
        else:
            shapes[PATH].append((to_px(ln["points"]), PATH_WIDTH))
            stats["unnamed path km"] += length(ln["points"]) / 1000
    return shapes, stats


def index(shapes):
    """For each tile, the pieces of every shape that can reach into it:
    {(col, row): [(layer, pixel points, width)]}. A line is cut into runs of
    consecutive segments near the tile; a run's cut ends lie outside it."""
    tiles = defaultdict(list)
    for li, colour in enumerate(LAYERS):
        for p, w in shapes[colour]:
            m = (w or 0.0) / 2 + 2.0
            if w is None:
                (c0, r0), (c1, r1) = (np.floor((p.min(0) - m) / TILE).astype(int).clip(0, TILES - 1),
                                      np.floor((p.max(0) + m) / TILE).astype(int).clip(0, TILES - 1))
                for c in range(c0, c1 + 1):
                    for r in range(r0, r1 + 1):
                        tiles[(c, r)].append((li, p, None))
                continue
            a, b = p[:-1], p[1:]
            lo = np.floor((np.minimum(a, b) - m) / TILE).astype(int).clip(0, TILES - 1)
            hi = np.floor((np.maximum(a, b) + m) / TILE).astype(int).clip(0, TILES - 1)
            segs = defaultdict(list)
            for s in range(len(a)):
                for c in range(lo[s, 0], hi[s, 0] + 1):
                    for r in range(lo[s, 1], hi[s, 1] + 1):
                        segs[(c, r)].append(s)
            for key, ss in segs.items():
                start = prev = ss[0]
                for s in ss[1:] + [None]:
                    if s is not None and s == prev + 1:
                        prev = s
                        continue
                    tiles[key].append((li, p[start:prev + 2], w))
                    if s is not None:
                        start = prev = s
    return tiles


def render(col, row, parts):
    """One tile as a 512 x 512 RGBA array: solid colours, alpha 0 or 255."""
    n = TILE * SS
    origin = np.array([col * TILE, row * TILE], np.float64)
    masks = {}
    for li, p, w in parts:
        if li not in masks:
            im = Image.new("L", (n, n), 0)
            masks[li] = (im, ImageDraw.Draw(im))
        d = masks[li][1]
        # Pixel k covers [k, k + 1); PIL puts pixel centres on whole coordinates.
        pts = [tuple(v) for v in ((p - origin) * SS - 0.5).tolist()]
        if w is None:
            d.polygon(pts, fill=255)
            continue
        ww = max(1, int(round(w * SS)))
        d.line(pts, fill=255, width=ww, joint="curve")
        r = (ww - 1) / 2.0
        for x, y in (pts[0], pts[-1]):                      # round ends
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    rgb = np.zeros((TILE, TILE, 3), np.float32)             # premultiplied
    alpha = np.zeros((TILE, TILE), np.float32)
    for li in sorted(masks):
        k = np.asarray(masks[li][0].reduce(SS), np.float32) / 255.0
        rgb = rgb * (1 - k)[..., None] + np.array(LAYERS[li], np.float32) * k[..., None]
        alpha = alpha * (1 - k) + k
    out = np.zeros((TILE, TILE, 4), np.uint8)
    on = alpha >= 0.5
    out[on, :3] = np.clip(rgb[on] / alpha[on, None] + 0.5, 0, 255).astype(np.uint8)
    out[on, 3] = 255
    return out


def preview_block(tile):
    """A tile reduced 8 x: each block's strongest alpha, its opaque pixels' mean colour."""
    f = TILE * TILES // PREVIEW
    t = tile.reshape(TILE // f, f, TILE // f, f, 4).astype(np.float32)
    a = t[..., 3] / 255.0
    wsum = a.sum(axis=(1, 3))
    rgb = (t[..., :3] * a[..., None]).sum(axis=(1, 3)) / np.maximum(wsum, 1e-6)[..., None]
    return np.dstack([rgb, a.max(axis=(1, 3)) * 255]).astype(np.uint8)


def convert(exe, src, dst):
    if os.path.isfile(dst):
        os.remove(dst)
    run = subprocess.run([exe, src, dst], capture_output=True, text=True, errors="replace", timeout=120)
    if not os.path.isfile(dst):
        return "%s: exit %s %s" % (os.path.basename(src), run.returncode, (run.stdout + run.stderr).strip()[-200:])
    return None


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    exe = sys.argv[1]
    work = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SRC, "usermap", "tiles")
    out_dir = os.path.join(ROOT, "data", "usermap")
    prev_dir = os.path.join(SRC, "usermap")
    if os.path.abspath(work).lower().startswith(os.path.abspath(os.path.join(ROOT, "data")).lower() + os.sep):
        sys.exit("keep the work folder out of data/ (it would be packed)")
    for d in (work, out_dir, prev_dir):
        os.makedirs(d, exist_ok=True)

    shapes, stats = load()
    for k in sorted(stats):
        print("  %-18s %8.1f" % (k, stats[k]))
    tiles = index(shapes)

    f = TILE * TILES // PREVIEW
    canvas = np.zeros((PREVIEW, PREVIEW, 4), np.uint8)
    jobs, drawn = [], 0

    def one(key):
        col, row = key
        name = "s_%03d_%03d_lco" % (col, row)
        tile = render(col, row, tiles[key]) if key in tiles else None
        png = os.path.join(work, name + ".png")
        if tile is None or not tile[..., 3].any():
            Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(png)
            return name, None
        Image.fromarray(tile, "RGBA").save(png)
        return name, preview_block(tile)

    keys = [(c, r) for r in range(TILES) for c in range(TILES)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 2)) as pool:
        for i, ((col, row), (name, block)) in enumerate(zip(keys, pool.map(one, keys)), 1):
            jobs.append(name)
            if block is not None:
                drawn += 1
                s = TILE // f
                canvas[row * s:(row + 1) * s, col * s:(col + 1) * s] = block
            if i % 128 == 0:
                print("tiles drawn: %d / %d" % (i, len(keys)), flush=True)
    print("%d tiles with something on them, %d empty" % (drawn, len(keys) - drawn))

    # Preview over the satellite, lightened a little so the lines read.
    sat = np.asarray(Image.open(os.path.join(SRC, "satellite_preview.png")).convert("RGB")
                     .resize((PREVIEW, PREVIEW), Image.LANCZOS), np.float32)
    sat = sat * 0.75 + 255 * 0.25
    a = canvas[..., 3:4].astype(np.float32) / 255.0
    view = sat * (1 - a) + canvas[..., :3].astype(np.float32) * a
    Image.fromarray(np.clip(view + 0.5, 0, 255).astype(np.uint8)).save(
        os.path.join(prev_dir, "usermap_preview.png"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 2)) as pool:
        failed = [e for e in pool.map(lambda n: convert(exe, os.path.join(work, n + ".png"),
                                                        os.path.join(out_dir, n + ".paa")), jobs) if e]
    if failed:
        sys.exit("ImageToPAA failed on %d tiles, e.g.\n  %s" % (len(failed), "\n  ".join(failed[:5])))
    paa = [os.path.join(out_dir, n + ".paa") for n in jobs]
    print("written: %d tiles in %s, %.1f MB" % (len(paa), out_dir, sum(os.path.getsize(p) for p in paa) / 1e6))


if __name__ == "__main__":
    main()
