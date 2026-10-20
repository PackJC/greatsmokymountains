"""Build the world and its layers from the sources, as Terrain Builder's export does.

    python tools/build_world.py <heights wrp> source <out folder> <ImageToPAA.exe> <work folder>
        [--objects FILE ...] [--models FOLDER ...]

<heights wrp> is any world with the map's heights (binarized OPRW or editable
8WVR). From source/ it reads satellite.png, mask.png and layers.cfg. Writes:
  <out>/greatsmokymountains.wrp      editable world (8WVR): heights, a material per
                                40 m cell, and every object from --objects
  <out>/data/layers/            s_/m_ tiles (.paa, via ImageToPAA) and P_ materials
--objects are Terrain Builder object imports ("template";x;y;yaw;pitch;roll;scale;height,
easting + 200000, height relative to the ground). Templates are model file names
found under the --models folders (searched under P:\\ for their game paths).

Tiles are 512 px with 16 px overlap, stepping 480 px (12 cells of 40 m). Each
tile gets up to four surfaces in layers.cfg order as slots: black, red, green,
blue in its mask. A tile with one or two surfaces uses two slots. Each cell's
material names the slots that occur in the cell.
"""

import argparse
import concurrent.futures
import glob
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from layer_rvmat import layer_rvmat, TILE, STEP, OVERLAP  # noqa: E402
from wvr import write_8wvr, read_8wvr, transform  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
PREFIX = "greatsmokymountains"
EASTING = 200000.0
CELL = 40
SLOT_COLOURS = np.array([(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)], np.uint8)


def read_layers_cfg(path):
    text = open(path).read()
    layers = re.findall(r"class\s+(\w+)\s*\{\s*texture\s*=\s*\"[^\"]*\";\s*material\s*=\s*\"([^\"]*)\"", text)
    colours = dict((n, (int(r), int(g), int(b))) for n, r, g, b in
                   re.findall(r"(\w+)\[\]\s*=\s*\{\{(\d+),(\d+),(\d+)\}\}", text))
    return [(name, mat, colours[name]) for name, mat in layers]


def load_heights(path):
    with open(path, "rb") as fh:
        magic = fh.read(4)
    if magic == b"8WVR":
        w = read_8wvr(path)
        return w["elevation"], w["terrain"], w["land"], w["land_cell"]
    from oprw import OPRW
    w = OPRW(path)
    elev = np.frombuffer(w.elevation, "<f4").reshape(w.terrain_y, w.terrain_x)
    return elev, (w.terrain_x, w.terrain_y), (w.land_x, w.land_y), w.land_cell


def bilinear(grid, x, y):
    x0 = min(max(int(x), 0), grid.shape[1] - 2)
    y0 = min(max(int(y), 0), grid.shape[0] - 2)
    fx, fy = x - x0, y - y0
    return float(grid[y0, x0] * (1 - fx) * (1 - fy) + grid[y0, x0 + 1] * fx * (1 - fy)
                 + grid[y0 + 1, x0] * (1 - fx) * fy + grid[y0 + 1, x0 + 1] * fx * fy)


def find_models(folders):
    models = {}
    for folder in folders:
        for f in glob.glob(os.path.join(folder, "**", "*.p3d"), recursive=True):
            full = os.path.abspath(f)
            game = os.path.relpath(full, "P:\\") if full.upper().startswith("P:\\") else None
            if game is None:
                sys.exit("--models folders must be on P: (got %s)" % folder)
            models.setdefault(os.path.splitext(os.path.basename(f))[0].lower(), game.lower())
    return models


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("heights")
    ap.add_argument("source")
    ap.add_argument("out")
    ap.add_argument("imagetopaa")
    ap.add_argument("work")
    ap.add_argument("--objects", nargs="*", default=[])
    ap.add_argument("--models", nargs="*", default=[])
    ap.add_argument("--elevation", help="heights to use instead (.npy, row 0 = south), e.g. carved by osm_water.py")
    ap.add_argument("--reuse-layers", action="store_true",
                    help="layers are unchanged: work out each cell's material but don't write tiles or materials")
    a = ap.parse_args()

    layers_dir = os.path.join(a.out, "data", "layers")
    os.makedirs(layers_dir, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)
    surfaces = read_layers_cfg(os.path.join(a.source, "layers.cfg"))
    names = [s[0] for s in surfaces]
    folders = {name: mat.replace("/", "\\").rsplit("\\", 1)[0] for name, mat, _ in surfaces}   # textures sit by the rvmat
    elev, terrain, land, land_cell = load_heights(a.heights)
    if a.elevation:
        elev = np.load(a.elevation)
        if elev.shape != (terrain[1], terrain[0]):
            sys.exit("--elevation must be %d x %d" % (terrain[1], terrain[0]))
    size = int(round(land[0] * land_cell))
    cell_px = int(land_cell)
    cells_per_tile = STEP // cell_px

    rgb = np.asarray(Image.open(os.path.join(a.source, "mask.png")).convert("RGB"))
    key = (rgb[..., 0].astype(np.uint32) << 16) | (rgb[..., 1].astype(np.uint32) << 8) | rgb[..., 2]
    mask = np.full(key.shape, 255, np.uint8)
    for i, (_, _, (r, g, b)) in enumerate(surfaces):
        mask[key == ((r << 16) | (g << 8) | b)] = i
    del rgb, key
    if (mask == 255).any():
        sys.exit("mask.png has colours that aren't in layers.cfg")
    sat = np.asarray(Image.open(os.path.join(a.source, "satellite.png")).convert("RGB"))
    if mask.shape != (size, size) or sat.shape[:2] != (size, size):
        sys.exit("satellite and mask must be %d x %d" % (size, size))

    mat_names = [""]
    mat_index = {}
    materials = np.zeros((land[1], land[0]), np.uint16)
    ntiles = -(-size // STEP)
    jobs = []
    for row in range(ntiles):
        for col in range(ntiles):
            ys = np.clip(np.arange(row * STEP - OVERLAP, row * STEP - OVERLAP + TILE), 0, size - 1)
            xs = np.clip(np.arange(col * STEP - OVERLAP, col * STEP - OVERLAP + TILE), 0, size - 1)
            win = mask[np.ix_(ys, xs)]
            present = sorted(set(np.unique(win).tolist()))
            if len(present) > 4:
                sys.exit("tile %d,%d has %d surfaces; at most 4" % (col, row, len(present)))
            nslots = 2 if len(present) <= 2 else 4
            slot_of = {s: k for k, s in enumerate(present)}
            lut = np.zeros(len(surfaces), np.uint8)
            for s, k in slot_of.items():
                lut[s] = k
            tile = "%03d_%03d" % (col, row)
            if not a.reuse_layers:
                m_img = SLOT_COLOURS[lut[win]]
                if len(present) == 1:
                    m_img = m_img[:4, :4]
                Image.fromarray(m_img).save(os.path.join(a.work, "m_%s_lco.png" % tile), compress_level=1)
                Image.fromarray(sat[np.ix_(ys, xs)]).save(os.path.join(a.work, "s_%s_lco.png" % tile), compress_level=1)
                jobs += [("m_%s_lco" % tile), ("s_%s_lco" % tile)]

            for cy in range(cells_per_tile):
                for cx in range(cells_per_tile):
                    i, jn = col * cells_per_tile + cx, row * cells_per_tile + cy
                    if i >= land[0] or jn >= land[1]:
                        continue
                    y0, x0 = jn * cell_px, i * cell_px
                    here = np.unique(mask[max(0, y0 - 1):y0 + cell_px + 1, max(0, x0 - 1):x0 + cell_px + 1])
                    slot_surf = [None] * nslots
                    for s in here.tolist():
                        slot_surf[slot_of[s]] = names[s]
                    tokens = ["l%02d" % (present[k] + 1) if slot_surf[k] else "n" for k in range(nslots)]
                    name = "p_%03d-%03d_%s" % (col, row, "_".join(tokens))
                    if name not in mat_index:
                        mat_index[name] = len(mat_names)
                        mat_names.append("%s\\data\\layers\\%s.rvmat" % (PREFIX, name))
                        if not a.reuse_layers:
                            with open(os.path.join(layers_dir, name + ".rvmat"), "w", newline="\n") as fh:
                                fh.write(layer_rvmat(PREFIX, col, row, slot_surf, folders))
                    materials[land[1] - 1 - jn, i] = mat_index[name]
        print("tiles: row %d / %d" % (row + 1, ntiles), flush=True)
    del sat, mask

    def convert(stem):
        dst = os.path.join(layers_dir, stem + ".paa")
        subprocess.run([a.imagetopaa, os.path.join(a.work, stem + ".png"), dst],
                       capture_output=True, timeout=300)
        return None if os.path.isfile(dst) else stem
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 2)) as pool:
        failed = [s for s in pool.map(convert, jobs) if s]
    if failed:
        sys.exit("ImageToPAA failed on %d tiles, e.g. %s" % (len(failed), failed[:5]))
    print("tiles converted: %d" % len(jobs) if jobs else "tiles reused")

    models = find_models(a.models)
    missing = {}
    for path in a.objects:                       # check every template first: millions of lines follow
        for line in open(path):
            tpl = line.split(";", 1)[0].strip().strip('"').lower()
            if tpl and tpl not in models:
                missing[tpl] = missing.get(tpl, 0) + 1
    if missing:
        sys.exit("templates with no model under --models: %s" % missing)

    def objects():
        k = 0
        cx, cz = size / terrain[0], size / terrain[1]
        for path in a.objects:
            for line in open(path):
                parts = line.strip().rstrip(";").split(";")
                if len(parts) < 8:
                    continue
                x, y, yaw, pitch, roll, scale, rel = (float(v) for v in parts[1:8])
                mx, mz = x - EASTING, y
                h = bilinear(elev, mx / cx, mz / cz) + rel
                k += 1
                yield models[parts[0].strip('"').lower()], transform(mx, h, mz, yaw, pitch, roll, scale), k

    wrp = os.path.join(a.out, PREFIX + ".wrp")
    n = write_8wvr(wrp, land, terrain, land_cell, elev, materials, mat_names, objects())
    check = read_8wvr(wrp, count_only=True)
    if check["trailing"] or check["object_count"] != n or len(check["mat_names"]) != len(mat_names):
        sys.exit("8WVR read-back mismatch")
    print("world: %s  materials %d  objects %d" % (wrp, len(mat_names) - 1, n))


if __name__ == "__main__":
    main()
