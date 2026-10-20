"""Paint roads, trails and streambeds into the mask and satellite, lined up with the terrain.

    python tools/paint_roads.py source source/roads/lines.json [source/water/lines.json [source/forest/zones.npy
        [source/buildings/footprints.json]]]

With forest zones (tools/forest.py), the original map's forest floor
(cp_conifer_moss1) first becomes each zone's own floor, whose clutter is the
grass and undergrowth under those trees; open ground becomes this map's
wildflower meadow (gsm_meadow, see MEADOW).

Reads source/satellite_base.png and source/mask_base.png (the images exactly as
tools/rebuild_layers.py rebuilt them; made from satellite.png and mask.png on
the first run) and writes source/satellite.png, source/mask.png,
source/layers.cfg and previews in source/roads/.

1. Shifts satellite and mask together by SHIFT. The compiled map's imagery sits
   about 7 m south and 1 m east of its own terrain: roads in the picture line up
   with OpenStreetMap only after that shift, the same in every quarter of the
   map, while the terrain matches real elevations with no shift (tools/georef.py).
2. Paints each road and trail into the mask with a surface that has no tall
   clutter, at about the width of its road parts.
3. Darkens a 2 m line into the satellite along every trail (roads are already
   in the imagery).
4. Keeps every 512 px layer tile (16 px overlap) to at most MAX_PER_TILE
   surfaces, as DayZ's terrain shaders allow: each tile keeps its road, trail
   and streambed surfaces and its most common natural ones, and the rest of its
   natural surfaces fold into those.
"""

import json
import os
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rebuild_layers import SURFACES, write_layers_cfg, TILE, STEP, OVERLAP  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
SIZE = 20480
SHIFT = (-1, 7)                  # metres to move the imagery: west 1, north 7
MAX_PER_TILE = 4

NATURAL = [SURFACES[k] for k in SURFACES]
# Forest floors added for tools/forest.py's zones (natural, so they may fold).
FOREST_FLOORS = [("cp_broadleaf_dense1", r"DZ\surfaces\data\terrain\cp_broadleaf_dense1.rvmat", (100, 140, 30)),
                 ("cp_broadleaf_dense2", r"DZ\surfaces\data\terrain\cp_broadleaf_dense2.rvmat", (170, 190, 90))]
ZONE_ORDER = ["open", "sprucefir", "northern", "cove", "oakpine", "mixed"]       # tools/forest.py ZONES
ZONE_FLOOR = {"sprucefir": "cp_conifer_moss1", "northern": "cp_broadleaf_sparse2", "cove": "cp_broadleaf_dense1",
              "oakpine": "cp_broadleaf_sparse1", "mixed": "cp_broadleaf_dense2"}
# Two road-like surfaces only, so every tile keeps room for natural ones: asphalt,
# and dirt under trails, dirt and gravel roads and streambeds (the gravel road
# parts and the water pieces show on top of it).
ROAD_SURFACES = {
    "cp_concrete1": None,                                        # already in the map
    "cp_dirt": ("cp_dirt", r"DZ\surfaces\data\terrain\cp_dirt.rvmat", (150, 110, 70)),
}
# The natural surface every tile keeps, so overlapping tiles always share one.
SHARED_FLOOR = "cp_broadleaf_dense1"
# Meadows: the open ground (the original map's cp_grass_tall) becomes this map's own wildflower
# meadow, gsm_meadow: Livonia's summer meadow grass texture under its own name, so config.cpp's
# CfgSurfaces can give it its own clutter (CfgSurfaceCharacters gsm_meadow: about a third white,
# yellow and purple flowers, St John's wort and thistle in the grass). One surface, so it takes
# no more of a tile's four slots than the grass did. Writes data/surfaces/ (its rvmat, and the
# two textures copied from DZ\surfaces_bliss under the new name, which CfgSurfaces matches).
OPEN_GROUND = "cp_grass_tall"
MEADOW = ("gsm_meadow", r"greatsmokymountains\data\surfaces\gsm_meadow.rvmat", (150, 210, 90))
MEADOW_FROM = r"P:\DZ\surfaces_bliss\data\terrain\en_grass1"
# waterway class -> painted streambed width in metres (tools/osm_water.py), drawn first
STREAMBEDS = [("seasonal", "cp_dirt", 2), ("brook", "cp_dirt", 7), ("stream", "cp_dirt", 8),
              ("river", "cp_dirt", 15)]
# family -> (mask surface, painted width in metres), drawn in this order (later wins)
PAINT = [
    ("trail", "cp_dirt", 2),
    ("mud", "cp_dirt", 4),
    ("grav", "cp_dirt", 5),
    ("asf3", "cp_concrete1", 6),
    ("asf2", "cp_concrete1", 8),
    ("asf1", "cp_concrete1", 11),
]
TRAIL_COLOUR = np.array([112, 92, 68], np.float32)
TRAIL_STRENGTH = 0.45


def shift_image(a, dx, dy):
    """Move image content dx px right and dy px up, repeating the edge into the gap."""
    out = np.roll(a, (-dy, dx), axis=(0, 1))
    if dy > 0:
        out[-dy:] = out[-dy - 1]
    elif dy < 0:
        out[:-dy] = out[-dy]
    if dx < 0:
        out[:, dx:] = out[:, dx - 1:dx]
    elif dx > 0:
        out[:, :dx] = out[:, dx:dx + 1]
    return out


def to_px(points):
    return [(x, SIZE - z) for x, z in points]


def wide_line(draw, pts, fill, width):
    """A wide polyline with a disc on every point: PIL's own leaves pixel cracks at its
    joints, where grass would show through the road's paint."""
    draw.line(pts, fill=fill, width=width, joint="curve")
    r = width / 2.0
    if width > 2:
        for cx, cz in pts:
            draw.ellipse([cx - r, cz - r, cx + r, cz + r], fill=fill)


def main():
    src, lines_path = sys.argv[1:3]
    water = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else []
    zones = np.load(sys.argv[4]) if len(sys.argv) > 4 else None
    footprints = json.load(open(sys.argv[5])) if len(sys.argv) > 5 else []   # tools/buildings.py
    roads_dir = os.path.dirname(lines_path)
    for name in ("satellite", "mask"):
        base = os.path.join(src, name + "_base.png")
        if not os.path.isfile(base):
            shutil.copyfile(os.path.join(src, name + ".png"), base)
    lines = json.load(open(lines_path))
    # Roads as built (tools/road_build.py) follow OSM's line within about a metre;
    # paint those, so the surface lies exactly under the parts. Trails stay OSM's.
    built_path = os.path.join(roads_dir, "centerlines.json")
    if os.path.isfile(built_path):
        built = [{"family": ln["family"], "points": [p[:2] for p in ln["points"]]}
                 for ln in json.load(open(built_path))]
        lines = built + [ln for ln in lines if ln["family"] == "trail"]

    surfaces = NATURAL + [s for s in ROAD_SURFACES.values() if s] + \
        (FOREST_FLOORS + [MEADOW] if zones is not None else [])
    colour_of = {cls: col for cls, _, col in surfaces}
    palette = np.array([col for _, _, col in surfaces], np.uint8)
    road_idx = {i for i, (cls, _, _) in enumerate(surfaces) if cls in ROAD_SURFACES}

    # Mask: palette indices, shifted, then roads painted on top.
    rgb = np.asarray(Image.open(os.path.join(src, "mask_base.png")).convert("RGB"))
    key = (rgb[..., 0].astype(np.uint32) << 16) | (rgb[..., 1].astype(np.uint32) << 8) | rgb[..., 2]
    idx = np.full(key.shape, 255, np.uint8)
    for i, (_, _, (r, g, b)) in enumerate(surfaces):
        idx[key == ((r << 16) | (g << 8) | b)] = i
    del rgb, key
    if (idx == 255).any():
        sys.exit("mask_base.png has colours that aren't in the surface list")
    idx = shift_image(idx, *SHIFT)
    if zones is not None:
        index_of = {s[0]: i for i, s in enumerate(surfaces)}
        lut = np.full(len(ZONE_ORDER), 255, np.uint8)
        for k, z in enumerate(ZONE_ORDER):
            if z in ZONE_FLOOR:
                lut[k] = index_of[ZONE_FLOOR[z]]
        scale = SIZE // zones.shape[0]
        moss = index_of["cp_conifer_moss1"]
        for y in range(0, SIZE, 2048):                     # in bands: the full upsample is 420 MB
            band = lut[np.repeat(np.repeat(zones[y // scale:(y + 2048) // scale], scale, 0), scale, 1)]
            sel = (idx[y:y + 2048] == moss) & (band != 255)
            idx[y:y + 2048][sel] = band[sel]
        # Meadows: the open ground becomes this map's wildflower meadow.
        idx[idx == index_of[OPEN_GROUND]] = index_of[MEADOW[0]]
        surf_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "surfaces")
        os.makedirs(surf_dir, exist_ok=True)
        for kind in ("_ca", "_nopx"):
            shutil.copyfile(MEADOW_FROM + kind + ".paa", os.path.join(surf_dir, MEADOW[0] + kind + ".paa"))
        rv = open(MEADOW_FROM + ".rvmat").read().replace(os.path.basename(MEADOW_FROM) + "_",
                                                          MEADOW[0] + "_")
        rv = rv.replace("dz\\surfaces_bliss\\data\\terrain\\", "greatsmokymountains\\data\\surfaces\\")
        with open(os.path.join(surf_dir, MEADOW[0] + ".rvmat"), "w", newline="\n") as fh:
            fh.write(rv)
    im = Image.fromarray(idx, "L")
    draw = ImageDraw.Draw(im)
    for cls, surface, width in STREAMBEDS:
        value = [i for i, s in enumerate(surfaces) if s[0] == surface][0]
        for ln in water:
            if ln["class"] == cls:
                wide_line(draw, to_px(ln["points"]), value, width)
    for family, surface, width in PAINT:
        value = [i for i, s in enumerate(surfaces) if s[0] == surface][0]
        for ln in lines:
            if ln["family"] == family:
                wide_line(draw, to_px(ln["points"]), value, width)
    for fp in footprints:                        # under buildings: no grass through floors
        value = [i for i, s in enumerate(surfaces) if s[0] == fp["surface"]][0]
        draw.polygon(to_px(fp["corners"]), fill=value)
    idx = np.asarray(im).copy()
    del im, draw

    # Keep each layer tile within MAX_PER_TILE surfaces. Each tile allows every road,
    # trail and streambed surface in it, the shared floor, and its most common other
    # natural ones, up to the limit. Tiles overlap, so a pixel may only keep a surface
    # that every tile covering it allows; otherwise it takes the most common natural
    # surface they all allow (the shared floor at least).
    shared = [i for i, s in enumerate(surfaces) if s[0] == SHARED_FLOOR] if zones is not None else []
    ntiles = -(-SIZE // STEP)
    if len(surfaces) > 16:
        sys.exit("more than 16 surfaces: widen the allowed-surface masks")
    allowed = np.full(idx.shape, 0xFFFF, np.uint16)
    for row in range(ntiles):
        for col in range(ntiles):
            y0, x0 = max(0, row * STEP - OVERLAP), max(0, col * STEP - OVERLAP)
            y1, x1 = row * STEP - OVERLAP + TILE, col * STEP - OVERLAP + TILE
            counts = np.bincount(idx[y0:y1, x0:x1].ravel(), minlength=len(surfaces))
            present = [int(i) for i in np.nonzero(counts)[0]]
            keep = [i for i in present if i in road_idx] + shared
            keep += sorted((i for i in present if i not in road_idx and i not in shared),
                           key=lambda i: -counts[i])[:MAX_PER_TILE - len(keep)]
            allowed[y0:y1, x0:x1] &= np.uint16(sum(1 << i for i in keep))
    total = np.bincount(idx.ravel(), minlength=len(surfaces))
    priority = sorted((i for i in range(len(surfaces)) if i not in road_idx), key=lambda i: -total[i]) + sorted(road_idx)
    replace = np.array([next((i for i in priority if m >> i & 1), 255) for m in range(1 << len(surfaces))], np.uint8)
    bad = ((allowed >> idx) & 1) == 0
    folded = int(bad.sum())
    if (replace[allowed[bad]] == 255).any():
        sys.exit("a pixel has no surface every tile over it allows")
    idx[bad] = replace[allowed[bad]]
    del allowed, bad

    Image.fromarray(palette[idx]).save(os.path.join(src, "mask.png"), compress_level=6)
    share = np.bincount(idx.ravel(), minlength=len(surfaces)) / idx.size

    # Satellite: shifted, with trails darkened in.
    sat = shift_image(np.asarray(Image.open(os.path.join(src, "satellite_base.png")).convert("RGB")), *SHIFT)
    alpha = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(alpha)
    for ln in lines:
        if ln["family"] == "trail":
            draw.line(to_px(ln["points"]), fill=255, width=2, joint="curve")
    alpha = np.asarray(alpha.filter(ImageFilter.GaussianBlur(0.6)))
    for y in range(0, SIZE, 1024):
        a = alpha[y:y + 1024, :, None].astype(np.float32) * (TRAIL_STRENGTH / 255.0)
        band = sat[y:y + 1024].astype(np.float32)
        sat[y:y + 1024] = (band * (1 - a) + TRAIL_COLOUR * a + 0.5).astype(np.uint8)
    Image.fromarray(sat).save(os.path.join(src, "satellite.png"), compress_level=1)

    write_layers_cfg(os.path.join(src, "layers.cfg"), surfaces, [
        "Rebuilt from smokymountains.wrp, plus road, trail, streambed and forest floor surfaces from tools/paint_roads.py.",
        "Legend colours are new; the originals are not stored in the map.",
        "Original layer numbers: %s" % ", ".join("%s = %s" % (k.upper(), SURFACES[k][0]) for k in SURFACES),
    ])

    # Previews: whole map with lines, and Mt Le Conte's trails at full resolution.
    small = Image.fromarray(sat).resize((2048, 2048), Image.LANCZOS)
    d = ImageDraw.Draw(small)
    k = 2048 / SIZE
    for ln in water:
        if ln["class"] in ("river", "stream", "brook"):
            d.line([(x * k, (SIZE - z) * k) for x, z in ln["points"]], fill=(60, 150, 255),
                   width=3 if ln["class"] == "river" else 1)
    for family, colour, width in (("trail", (255, 80, 40), 2), ("mud", (255, 210, 0), 2), ("grav", (255, 210, 0), 2),
                                  ("asf3", (255, 240, 160), 2), ("asf2", (255, 255, 255), 3), ("asf1", (255, 255, 255), 4)):
        for ln in lines:
            if ln["family"] == family:
                d.line([(x * k, (SIZE - z) * k) for x, z in ln["points"]], fill=colour, width=width)
    small.save(os.path.join(roads_dir, "preview_map.png"))

    cx, cz, half = 9600, 8600, 1536
    box = (cx - half, SIZE - cz - half, cx + half, SIZE - cz + half)
    crop_sat = Image.fromarray(sat[box[1]:box[3], box[0]:box[2]])
    crop_mask = Image.fromarray(palette[idx[box[1]:box[3], box[0]:box[2]]])
    sheet = Image.new("RGB", (2 * 1536, 1536))
    sheet.paste(crop_sat.resize((1536, 1536), Image.LANCZOS), (0, 0))
    sheet.paste(crop_mask.resize((1536, 1536), Image.NEAREST), (1536, 0))
    sheet.save(os.path.join(roads_dir, "preview_leconte.png"))

    print("imagery shifted %+d m east, %+d m north" % SHIFT)
    print("pixels refolded to keep tiles within %d surfaces: %d (%.3f%% of the map)"
          % (MAX_PER_TILE, folded, 100.0 * folded / idx.size))
    for (cls, _, _), s in zip(surfaces, share):
        print("  %-22s %6.2f%%" % (cls, 100 * s))


if __name__ == "__main__":
    main()
