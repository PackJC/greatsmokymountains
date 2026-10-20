"""Stitch the satellite and surface mask back together from the map's layer tiles.

    python tools/rebuild_layers.py smokymountains.wrp <tile pngs> source

<tile pngs> holds the s_*/m_* tiles as PNG (tools/paa_to_png.py). Writes into <out>:
  satellite.png        the full satellite image, north at the top
  mask.png             one legend colour per surface, north at the top
  layers.cfg           the surfaces and their legend colours, for Terrain Builder
  satellite_preview.png, mask_preview.png   2048 px previews

How the tiles work: each tile is 512 m with 16 m overlap on every side, so
tiles step 480 m (12 layer cells of 40 m). A tile's mask has up to four surface
slots: black = slot 1, red = slot 2, green = slot 3, blue = slot 4, with
in-between values blending. Each 40 m cell's material is named
P_<col>-<row>_<slot1>_<slot2>[_<slot3>_<slot4>] ("N" for an unused slot) and
names the slots that cell uses. Terrain Builder's mask is one colour per
surface, so each pixel takes the strongest of its cell's slots.
"""

import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oprw import OPRW  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

# Original layer index (L01..L13) -> (layers.cfg class, vanilla surface material, legend colour).
SURFACES = {
    "l01": ("cp_grass_tall", r"DZ\surfaces\data\terrain\cp_grass_tall.rvmat", (120, 200, 60)),
    "l07": ("cp_broadleaf_sparse1", r"DZ\surfaces\data\terrain\cp_broadleaf_sparse1.rvmat", (200, 160, 40)),
    "l08": ("cp_broadleaf_sparse2", r"DZ\surfaces\data\terrain\cp_broadleaf_sparse2.rvmat", (230, 110, 30)),
    "l09": ("cp_concrete1", r"DZ\surfaces\data\terrain\cp_concrete1.rvmat", (150, 150, 150)),
    "l11": ("cp_conifer_common1", r"DZ\surfaces\data\terrain\cp_conifer_common1.rvmat", (20, 110, 50)),
    "l13": ("cp_conifer_moss1", r"DZ\surfaces\data\terrain\cp_conifer_moss1.rvmat", (60, 160, 140)),
}

TILE, STEP, OVERLAP, CELL = 512, 480, 16, 40


def write_layers_cfg(path, surfaces, notes):
    """layers.cfg for Terrain Builder: one class per surface and its legend colour."""
    with open(path, "w", newline="\n") as fh:
        for line in notes:
            fh.write("// %s\n" % line)
        fh.write("class Layers\n{\n")
        for cls, mat, _ in surfaces:
            fh.write("\tclass %s\n\t{\n\t\ttexture = \"\";\n\t\tmaterial = \"%s\";\n\t};\n" % (cls, mat))
        fh.write("};\nclass Legend\n{\n\tpicture = \"\";\n\tclass Colors\n\t{\n")
        for cls, _, (cr, cg, cb) in surfaces:
            fh.write("\t\t%s[] = {{%d,%d,%d}};\n" % (cls, cr, cg, cb))
        fh.write("\t};\n};\n")


def parse_material(name):
    parts = os.path.splitext(os.path.basename(name))[0].lower().split("_")
    col, row = (int(v) for v in parts[1].split("-"))
    return col, row, parts[2:]


def load_tile(path):
    im = Image.open(path).convert("RGB")
    if im.size != (TILE, TILE):                         # flat tiles are stored tiny
        im = im.resize((TILE, TILE), Image.NEAREST)
    return np.asarray(im)


def main():
    wrp_path, tiles, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    w = OPRW(wrp_path)
    size = int(round(w.land_x * w.land_cell))           # metres = satellite pixels (1 m/px)
    ntiles = -(-size // STEP)

    # Surface slots per tile, gathered from every cell material in it.
    slots = {}
    for name in w.mat_names:
        if not name:
            continue
        col, row, toks = parse_material(name)
        cur = slots.setdefault((col, row), [None] * len(toks))
        for k, t in enumerate(toks):
            if t == "n":
                continue
            if t not in SURFACES:
                sys.exit("unknown surface %s in %s" % (t, name))
            if cur[k] not in (None, t):
                sys.exit("tile %d,%d: slot %d is both %s and %s" % (col, row, k + 1, cur[k], t))
            cur[k] = t

    order = list(SURFACES)
    palette = np.array([SURFACES[k][2] for k in order], dtype=np.uint8)
    sat = np.zeros((size, size, 3), np.uint8)
    mask_idx = np.zeros((size, size), np.uint8)
    counts = np.zeros(len(order), np.int64)

    for row in range(ntiles):
        for col in range(ntiles):
            s = load_tile(os.path.join(tiles, "s_%03d_%03d_lco.png" % (col, row)))
            m = load_tile(os.path.join(tiles, "m_%03d_%03d_lco.png" % (col, row))).astype(np.float32) / 255.0
            x0, y0 = col * STEP, row * STEP                 # image coords, y down from north
            x1, y1 = min(x0 + STEP, size), min(y0 + STEP, size)
            sat[y0:y1, x0:x1] = s[OVERLAP:OVERLAP + y1 - y0, OVERLAP:OVERLAP + x1 - x0]

            r, g, b = m[..., 0], m[..., 1], m[..., 2]
            weights = np.stack([np.clip(1.0 - r - g - b, 0, 1), r, g, b], axis=-1)
            lut = np.array([order.index(t) if t else 255 for t in slots[(col, row)]], np.uint8)

            for cy in range((y1 - y0) // CELL):
                for cx in range((x1 - x0) // CELL):
                    i = (x0 // CELL) + cx                    # land cell, south origin
                    j = w.land_y - 1 - (y0 // CELL) - cy
                    mcol, mrow, toks = parse_material(w.mat_names[w.materials.get(i, j)])
                    if (mcol, mrow) != (col, row):
                        sys.exit("cell %d,%d uses tile %d,%d's material, expected %d,%d" % (i, j, mcol, mrow, col, row))
                    present = [k for k, t in enumerate(toks) if t != "n"]
                    py, px = OVERLAP + cy * CELL, OVERLAP + cx * CELL
                    wsub = weights[py:py + CELL, px:px + CELL][..., present]
                    surf = lut[np.asarray(present)[wsub.argmax(axis=-1)]]
                    ys, xs = y0 + cy * CELL, x0 + cx * CELL
                    mask_idx[ys:ys + CELL, xs:xs + CELL] = surf
                    counts += np.bincount(surf.ravel(), minlength=len(order))
        print("row %d / %d" % (row + 1, ntiles), flush=True)

    Image.fromarray(sat).save(os.path.join(out, "satellite.png"), compress_level=1)
    mask = palette[mask_idx]
    Image.fromarray(mask).save(os.path.join(out, "mask.png"), compress_level=6)
    Image.fromarray(sat).resize((2048, 2048), Image.LANCZOS).save(os.path.join(out, "satellite_preview.png"))
    Image.fromarray(mask).resize((2048, 2048), Image.NEAREST).save(os.path.join(out, "mask_preview.png"))

    write_layers_cfg(os.path.join(out, "layers.cfg"), [SURFACES[k] for k in order], [
        "Rebuilt from smokymountains.wrp. Legend colours are new; the originals are not stored in the map.",
        "Original layer numbers: %s" % ", ".join("%s = %s" % (k.upper(), SURFACES[k][0]) for k in order),
    ])

    total = counts.sum()
    for k, n in zip(order, counts):
        print("  %-22s %5.1f%%" % (SURFACES[k][0], 100.0 * n / total))
    print("written to %s" % out)


if __name__ == "__main__":
    main()
