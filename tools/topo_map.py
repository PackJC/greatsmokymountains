"""Draw a printable topographic map of the terrain, in the style of the DayZ
Deluxe Edition's Chernarus map: relief, contours, forest, roads, hiking
trails, streams, buildings, symbols and names, a 1 km grid, a legend, a
locator inset and a title panel with a rendered view of the mountains.

    python tools/topo_map.py <out folder>

Writes <out>/GreatSmokyMountains_Map.pdf (A1 landscape, 1:36 000; vector lines
and text over a relief image), the relief image and the cover view as JPEG, and
a reduced PNG of the relief for a quick look. Everything comes from source/:
the map's own heights and placed objects (what players see in game) and the
OpenStreetMap names, trails and places the map was built from.
"""

import json
import math
import os
import sys
import zlib

import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import find_models  # noqa: E402
from geo import utm  # noqa: E402
from mission import MODEL_FOLDERS, osm_places, read_tb  # noqa: E402
from odol_info import odol_info  # noqa: E402
from render_view import render as render_view  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "source")
SIZE = 20480.0
RES = 8192                                   # relief image pixels per side (2.5 m)
MM = 72.0 / 25.4
PAGE_W, PAGE_H = 841 * MM, 594 * MM          # A1 landscape
SCALE = 36000
MAP_W = SIZE / SCALE * 1000 * MM
MX0, MY0 = 14 * MM, (PAGE_H - MAP_W) / 2
SX0, SX1 = MX0 + MAP_W + 14 * MM, PAGE_W - 8 * MM      # sidebar
LEG_ROWS, LEG_ROW_H, LEG_HEAD = 24, 7.0 * MM, 8 * MM          # sidebar: legend, inset, title panel
LEG_H = LEG_HEAD + 9 * MM + LEG_ROW_H * LEG_ROWS + 3 * MM
INSET_H = 98 * MM
PANEL_TOP, PANEL_BOT = PAGE_H - 8 * MM - LEG_H - 4 * MM - INSET_H - 4 * MM, 8 * MM
COVER_Y = PANEL_BOT + 30 * MM
COVER_H = PANEL_TOP - 22 * MM - COVER_Y
CONTOUR, INDEX = 20.0, 100.0
FONTS = {"N": "ARIALN.TTF", "NB": "ARIALNB.TTF", "NI": "ARIALNI.TTF", "NBI": "ARIALNBI.TTF",
         "A": "arial.ttf", "AB": "arialbd.ttf", "T": "impact.ttf"}

# Colours (0-255).
OPEN, FOREST, URBAN, WATER = (250, 250, 245), (176, 211, 140), (236, 222, 208), (156, 206, 240)
CONTOUR_RGB, ROCK_RGB = (196, 128, 72), (88, 82, 78)
BLUE_LINE, GRID = (40, 140, 215), (35, 95, 200)
GREEN_PANEL, RED = (24, 140, 76), (226, 38, 42)
TRAIL_COLOURS = [(226, 38, 42), (240, 190, 0), (30, 150, 60), (30, 100, 210)]


def rgb(c, a=1.0):
    return Color(c[0] / 255.0, c[1] / 255.0, c[2] / 255.0, alpha=a)


def P(x, z):
    """Map metres to page points."""
    return MX0 + x / SIZE * MAP_W, MY0 + z / SIZE * MAP_W


def to_map(lat, lon, geo):
    x, z = utm(lat, lon, 17)
    return x + geo["offset_x"], z + geo["offset_y"]


# ------------------------------------------------------------------ data

def load():
    d = {"geo": json.load(open(os.path.join(ROOT, "tools", "georef.json")))}
    d["elev"] = np.load(os.path.join(SRC, "buildings", "elevation.npy")).astype(np.float32)   # row 0 south
    d["roads"] = json.load(open(os.path.join(SRC, "roads", "lines.json")))
    d["water"] = json.load(open(os.path.join(SRC, "water", "lines.json")))
    d["places"] = osm_places()
    geo = d["geo"]
    d["ponds"], d["falls"] = [], []
    for e in json.load(open(os.path.join(SRC, "water", "osm_water.json"), encoding="utf-8"))["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("natural") == "water" and "geometry" in e:
            d["ponds"].append([to_map(g["lat"], g["lon"], geo) for g in e["geometry"]])
        elif e["type"] == "node" and t.get("waterway") == "waterfall" and t.get("name"):
            x, z = to_map(e["lat"], e["lon"], geo)
            if 0 < x < SIZE and 0 < z < SIZE and all(math.hypot(x - f[1], z - f[2]) > 60 for f in d["falls"]):
                d["falls"].append((t["name"], x, z))
    d["aerial"] = []
    d["towns_inset"] = []
    for e in json.load(open(os.path.join(SRC, "mission", "osm_mapextras.json"), encoding="utf-8"))["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("aerialway") in ("cable_car", "chair_lift", "gondola"):
            d["aerial"].append((t.get("name", ""), [to_map(g["lat"], g["lon"], geo) for g in e["geometry"]]))
        elif e["type"] == "node":
            d["towns_inset"].append((t.get("name", "").split(";")[0], e["lat"], e["lon"]))
    d["park"] = [[(g["lat"], g["lon"]) for g in e["geometry"]]
                 for e in json.load(open(os.path.join(SRC, "mission", "osm_park_boundary.json"),
                                         encoding="utf-8"))["elements"] if e["type"] == "way"]
    for e in json.load(open(os.path.join(SRC, "roads", "osm_highways.json"), encoding="utf-8"))["elements"]:
        if e.get("tags", {}).get("name") == "Gatlinburg SkyBridge" and "geometry" in e:
            d["skybridge"] = [to_map(g["lat"], g["lon"], geo) for g in e["geometry"]]
    # Placed objects: trees for forest cover, rocks, buildings.
    models = find_models(MODEL_FOLDERS)
    info = {}

    def bbox(tpl):
        if tpl not in info:
            info[tpl] = odol_info(os.path.join("P:\\", models[tpl]))
        return info[tpl]
    codes = {}
    c, rows = read_tb(os.path.join(SRC, "forest", "tb_trees.txt"), codes)
    d["trees"] = rows[:, :2].copy()
    del c, rows
    codes = {}
    c, rows = read_tb(os.path.join(SRC, "rocks", "tb_rocks.txt"), codes)
    names = {v: k for k, v in codes.items()}
    d["rocks"] = []
    for code in np.unique(c):
        tpl = names[code]
        if not tpl.startswith("rock_"):
            continue
        i = bbox(tpl)
        ext = max(i["max"][0] - i["min"][0], i["max"][2] - i["min"][2]) / 2
        for r in rows[c == code]:
            d["rocks"].append((r[0], r[1], ext * r[5]))
    d["buildings"] = []
    for f in ("tb_buildings.txt", "tb_cabins.txt", "tb_fuel.txt"):
        codes = {}
        c, rows = read_tb(os.path.join(SRC, "buildings", f), codes)
        names = {v: k for k, v in codes.items()}
        for code, r in zip(c, rows):
            tpl = names[code]
            i = bbox(tpl)
            (x0, _, z0), (x1, _, z1) = i["min"], i["max"]
            t = math.radians(r[2])
            ca, sa, s = math.cos(t), math.sin(t), r[5]
            corners = [(r[0] + s * (lx * ca + lz * sa), r[1] + s * (-lx * sa + lz * ca))
                       for lx, lz in ((x0, z0), (x1, z0), (x1, z1), (x0, z1))]
            d["buildings"].append((tpl, r[0], r[1], corners))
    print("data loaded: %d trees, %d cliff rocks, %d buildings" % (len(d["trees"]), len(d["rocks"]),
                                                                   len(d["buildings"])), flush=True)
    return d


def box_blur(a, r, passes=2):
    for _ in range(passes):
        for ax in (0, 1):
            p = np.pad(a, [(r + 1, r) if k == ax else (0, 0) for k in (0, 1)], mode="edge")
            cs = np.cumsum(p, axis=ax, dtype=np.float64)
            hi = cs.take(np.arange(2 * r + 1, cs.shape[ax]), axis=ax)
            lo = cs.take(np.arange(0, cs.shape[ax] - 2 * r - 1), axis=ax)
            a = ((hi - lo) / (2 * r + 1)).astype(np.float32)
    return a


def resample(grid, rows, n_out, north_up_src):
    """Bilinear sample of a square grid covering the map at output pixel centres (rows of an n_out image, north up)."""
    n = grid.shape[0]
    cell = SIZE / n
    xs = (np.arange(n_out) + 0.5) * SIZE / n_out
    zs = SIZE - (np.asarray(rows) + 0.5) * SIZE / n_out
    u = np.clip(xs / cell - (0.5 if north_up_src else 0.0), 0, n - 1.001)
    v = (SIZE - zs) / cell - 0.5 if north_up_src else zs / cell
    v = np.clip(v, 0, n - 1.001)
    i0, j0 = v.astype(int), u.astype(int)
    fv, fu = (v - i0)[:, None], (u - j0)[None, :]
    g00, g01 = grid[i0][:, j0], grid[i0][:, j0 + 1]
    g10, g11 = grid[i0 + 1][:, j0], grid[i0 + 1][:, j0 + 1]
    return (g00 * (1 - fu) * (1 - fv) + g01 * fu * (1 - fv) + g10 * (1 - fu) * fv + g11 * fu * fv).astype(np.float32)


# ------------------------------------------------------------------ relief image

def relief(d, out_jpg):
    elev = box_blur(d["elev"], 1, 2)                     # south up, 5 m
    d["elev_smooth"] = elev
    px = SIZE / RES
    # Forest: placed trees per 10 m cell, smoothed.
    n10 = 2048
    cnt = np.zeros((n10, n10), np.float32)
    t = d["trees"]
    np.add.at(cnt, (np.clip((SIZE - t[:, 1]) / 10, 0, n10 - 1).astype(int),
                    np.clip(t[:, 0] / 10, 0, n10 - 1).astype(int)), 1)
    dens = box_blur(cnt, 3, 2)                           # trees per 100 m2, north up
    forest = np.clip((dens - 0.12) / 0.25, 0, 1)
    # Urban: buildings per 10 m cell, smoothed wide.
    bc = np.zeros((n10, n10), np.float32)
    for tpl, x, z, corners in d["buildings"]:
        bc[min(int((SIZE - z) / 10), n10 - 1), min(int(x / 10), n10 - 1)] += 1
    urban = np.clip((box_blur(bc, 5, 2) * 121 - 1.5) / 2.0, 0, 1) * 0.85
    # Ponds and rocks, drawn at full size.
    water = Image.new("L", (RES, RES), 0)
    dw = ImageDraw.Draw(water)
    for poly in d["ponds"]:
        dw.polygon([(x / px, (SIZE - z) / px) for x, z in poly], fill=255)
    rocks = Image.new("L", (RES, RES), 0)
    dr = ImageDraw.Draw(rocks)
    for x, z, ext in d["rocks"]:
        r = min(max(ext * 0.6 / px, 1.2), 7.0)
        u, v = x / px, (SIZE - z) / px
        dr.polygon([(u, v - r), (u + r * 0.9, v + r * 0.6), (u - r * 0.9, v + r * 0.6)], fill=170)
    water, rocks = np.asarray(water), np.asarray(rocks)

    img = np.zeros((RES, RES, 3), np.uint8)
    lx, ly, lz = -math.cos(math.radians(45)) * 0.7071, math.cos(math.radians(45)) * 0.7071, math.sin(math.radians(45))
    strip = 512
    for r0 in range(0, RES, strip):
        rows = np.arange(r0 - 1, r0 + strip + 1)
        h = resample(elev, np.clip(rows, 0, RES - 1), RES, False)
        gy = (h[2:] - h[:-2]) / 2                        # per pixel, + southward
        gx = np.gradient(h[1:-1], axis=1)
        h = h[1:-1]
        g = np.hypot(gx, gy) + 1e-4
        nx, ny = -gx / px, gy / px                      # surface normal (east, north) with z = 1
        shade = (nx * lx + ny * ly + lz) / np.sqrt(nx * nx + ny * ny + 1) / lz
        f = resample(forest, np.arange(r0, r0 + strip), RES, True)[..., None]
        u = resample(urban, np.arange(r0, r0 + strip), RES, True)[..., None]
        col = np.array(OPEN, np.float32) * (1 - f) + np.array(FOREST, np.float32) * f
        col = col * (1 - u) + np.array(URBAN, np.float32) * u
        col *= np.clip(0.68 + 0.32 * shade, 0.5, 1.06)[..., None]
        wm = water[r0:r0 + strip, :, None] / 255.0
        col = col * (1 - wm) + np.array(WATER, np.float32) * wm
        # Contours: anti-aliased by distance to the level in pixels.
        di = np.abs(h / INDEX - np.round(h / INDEX)) * INDEX / g
        dm = np.abs(h / CONTOUR - np.round(h / CONTOUR)) * CONTOUR / g
        a_idx = np.clip(1.35 - di, 0, 1) * 0.95
        a_min = np.clip(0.85 - dm, 0, 1) * 0.8 * (di > 1.5)
        a = np.maximum(a_idx, a_min)[..., None] * (1 - wm)
        col = col * (1 - a) + np.array(CONTOUR_RGB, np.float32) * a
        ra = rocks[r0:r0 + strip, :, None] / 255.0
        col = col * (1 - ra) + np.array(ROCK_RGB, np.float32) * ra
        img[r0:r0 + strip] = np.clip(col, 0, 255).astype(np.uint8)
        print("relief rows %d / %d" % (r0 + strip, RES), flush=True)
    im = Image.fromarray(img)
    im.save(out_jpg, quality=90, subsampling=0)
    im.resize((2048, 2048), Image.LANCZOS).save(out_jpg.replace(".jpg", "_preview.png"))


# ------------------------------------------------------------------ cover view

def cover(out_jpg, w, h):
    """The title panel's view of Mt. Le Conte over the Gatlinburg hills, with every placed
    tree, bush, rock and building (tools/render_view.py)."""
    render_view(out_jpg, w, h)


# ------------------------------------------------------------------ PDF helpers

class Labels:
    """Places labels without overlaps (axis-aligned boxes in page points)."""

    def __init__(self):
        self.boxes = []

    def free(self, b):
        x0, y0, x1, y1 = b
        if x0 < MX0 + 2 or y0 < MY0 + 2 or x1 > MX0 + MAP_W - 2 or y1 > MY0 + MAP_W - 2:
            return False
        return not any(x0 < b1[2] and x1 > b1[0] and y0 < b1[3] and y1 > b1[1] for b1 in self.boxes)

    def take(self, b):
        self.boxes.append(b)


def text(c, x, y, s, font, size, fill, anchor="l", angle=0.0, halo=(255, 255, 255), halo_w=1.4, halo_a=0.85):
    w = pdfmetrics.stringWidth(s, font, size)
    dx = {"l": 0.0, "c": -w / 2, "r": -w}[anchor]
    c.saveState()
    c.translate(x, y)
    if angle:
        c.rotate(angle)
    if halo is not None:                    # own graphics state: ReportLab never writes "0 Tr" back
        c.saveState()
        t = c.beginText(dx, 0)
        t.setFont(font, size)
        t.setTextRenderMode(1)
        c.setStrokeColor(rgb(halo, halo_a))
        c.setLineWidth(halo_w)
        c.setLineJoin(1)
        t.textOut(s)
        c.drawText(t)
        c.restoreState()
    t = c.beginText(dx, 0)
    t.setFont(font, size)
    c.setFillColor(rgb(fill))
    t.textOut(s)
    c.drawText(t)
    c.restoreState()
    return w


def label(c, L, x, y, s, font, size, fill, offsets=((1, 0), (-1, 0), (0, 1), (0, -1)), gap=2.5, **kw):
    """Try the label right, left, above and below the point; returns True if placed."""
    w = pdfmetrics.stringWidth(s, font, size)
    hgt = size * 0.75
    for ox, oy in offsets:
        if ox > 0:
            bx, by, anchor = x + gap, y - hgt / 2, "l"
        elif ox < 0:
            bx, by, anchor = x - gap - w, y - hgt / 2, "r"
        else:
            bx, by, anchor = x - w / 2, y + (gap if oy > 0 else -gap - hgt), "c"
        b = (bx - 1, by - 1, bx + w + 1, by + hgt + 1)
        if L.free(b):
            L.take(b)
            text(c, x + gap if anchor == "l" else (x - gap if anchor == "r" else x), by, s, font, size, fill,
                 anchor=anchor, **kw)
            return True
    return False


def polyline(c, pts, close=False):
    p = c.beginPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if close:
        p.close()
    return p


def stroke_lines(c, lines, colour, width, dash=None, cap=1, alpha=1.0):
    if not lines:
        return
    c.saveState()
    c.setStrokeColor(rgb(colour, alpha))
    c.setLineWidth(width)
    c.setLineCap(cap)
    c.setLineJoin(1)
    if dash:
        c.setDash(dash)
    p = c.beginPath()
    for pts in lines:
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
    c.drawPath(p, stroke=1, fill=0)
    c.restoreState()


# Symbols, drawn centred at (x, y) page points with size s.
def sym_peak(c, x, y, s=4.0):
    c.setFillColor(rgb((40, 30, 25)))
    c.drawPath(polyline(c, [(x - s / 2, y - s * 0.35), (x + s / 2, y - s * 0.35), (x, y + s * 0.5)], True), stroke=0, fill=1)


def sym_tent(c, x, y, s=5.0):
    c.setStrokeColor(rgb((20, 20, 20)))
    c.setFillColor(rgb((255, 255, 255)))
    c.setLineWidth(0.7)
    c.drawPath(polyline(c, [(x - s / 2, y - s * 0.4), (x + s / 2, y - s * 0.4), (x, y + s * 0.45)], True), stroke=1, fill=1)
    c.line(x, y + s * 0.45, x, y - s * 0.4)


def sym_hut(c, x, y, s=4.5):
    c.setStrokeColor(rgb((20, 20, 20)))
    c.setFillColor(rgb((250, 250, 250)))
    c.setLineWidth(0.6)
    c.drawPath(polyline(c, [(x - s * 0.4, y - s * 0.45), (x + s * 0.4, y - s * 0.45), (x + s * 0.4, y),
                            (x, y + s * 0.45), (x - s * 0.4, y)], True), stroke=1, fill=1)


def sym_view(c, x, y, s=5.0):
    c.setStrokeColor(rgb(RED))
    c.setLineWidth(0.8)
    for k in range(4):
        a = math.radians(45 * k)
        c.line(x - math.cos(a) * s / 2, y - math.sin(a) * s / 2, x + math.cos(a) * s / 2, y + math.sin(a) * s / 2)


def sym_signpost(c, x, y, s=5.0):
    c.setStrokeColor(rgb((20, 20, 20)))
    c.setFillColor(rgb(RED))
    c.setLineWidth(0.6)
    c.line(x - s * 0.2, y - s / 2, x - s * 0.2, y + s / 2)
    c.drawPath(polyline(c, [(x - s * 0.2, y + s / 2), (x + s * 0.4, y + s * 0.35), (x - s * 0.2, y + s * 0.15)], True),
               stroke=0, fill=1)


def sym_letter(c, x, y, ch, bg, fg=(255, 255, 255), s=5.0, shape="square"):
    c.setFillColor(rgb(bg))
    c.setStrokeColor(rgb((255, 255, 255)))
    c.setLineWidth(0.4)
    if shape == "circle":
        c.circle(x, y, s / 2, stroke=1, fill=1)
    else:
        c.rect(x - s / 2, y - s / 2, s, s, stroke=1, fill=1)
    c.setFillColor(rgb(fg))
    c.setFont("AB", s * 0.72)
    c.drawCentredString(x, y - s * 0.26, ch)


def sym_cross(c, x, y, s=5.0):                       # church
    c.setStrokeColor(rgb((20, 20, 20)))
    c.setLineWidth(0.9)
    c.line(x, y - s / 2, x, y + s / 2)
    c.line(x - s * 0.3, y + s * 0.15, x + s * 0.3, y + s * 0.15)


def sym_firstaid(c, x, y, s=5.0):
    c.setFillColor(rgb((255, 255, 255)))
    c.setStrokeColor(rgb(RED))
    c.setLineWidth(0.5)
    c.rect(x - s / 2, y - s / 2, s, s, stroke=1, fill=1)
    c.setFillColor(rgb(RED))
    c.rect(x - s * 0.12, y - s * 0.35, s * 0.24, s * 0.7, stroke=0, fill=1)
    c.rect(x - s * 0.35, y - s * 0.12, s * 0.7, s * 0.24, stroke=0, fill=1)


def sym_fall(c, x, y, s=5.0):
    c.setStrokeColor(rgb((20, 100, 190)))
    c.setLineWidth(0.8)
    for k in (-1, 0, 1):
        c.bezier(x + k * s * 0.3, y + s / 2, x + k * s * 0.3 + s * 0.15, y + s * 0.1,
                 x + k * s * 0.3 - s * 0.15, y - s * 0.1, x + k * s * 0.3, y - s / 2)


def sym_historic(c, x, y, s=4.5):
    c.setFillColor(rgb((180, 40, 60)))
    c.rect(x - s / 2, y - s / 2, s, s * 0.6, stroke=0, fill=1)
    c.rect(x - s / 2, y + s * 0.1, s * 0.25, s * 0.35, stroke=0, fill=1)
    c.rect(x + s / 4, y + s * 0.1, s * 0.25, s * 0.35, stroke=0, fill=1)


def sym_ranger(c, x, y, s=5.0):
    sym_letter(c, x, y, "i", (24, 110, 60), s=s, shape="circle")


def sym_police(c, x, y, s=5.0):
    sym_letter(c, x, y, "P", (30, 60, 160), s=s, shape="circle")


def sym_fire(c, x, y, s=5.0):
    sym_letter(c, x, y, "F", RED, s=s, shape="circle")


def sym_fuel(c, x, y, s=5.0):
    sym_letter(c, x, y, "F", (40, 40, 40), s=s)


def sym_parking(c, x, y, s=4.5):
    sym_letter(c, x, y, "P", (40, 110, 200), s=s)


# ------------------------------------------------------------------ the page

def register_fonts():
    for name, f in FONTS.items():
        pdfmetrics.registerFont(TTFont(name, os.path.join(r"C:\Windows\Fonts", f)))


def trail_colour(name):
    if name == "Appalachian Trail":
        return RED
    return TRAIL_COLOURS[1 + zlib.crc32(name.encode()) % 3]


def draw_map(c, d, relief_jpg):
    L = Labels()
    c.drawImage(relief_jpg, MX0, MY0, MAP_W, MAP_W)
    c.saveState()
    clip = c.beginPath()
    clip.rect(MX0, MY0, MAP_W, MAP_W)
    c.clipPath(clip, stroke=0, fill=0)
    geo = d["geo"]
    pp = lambda pts: [P(x, z) for x, z in pts]

    # National park boundary.
    stroke_lines(c, [pp([to_map(la, lo, geo) for la, lo in w]) for w in d["park"]], (20, 110, 60), 2.2, alpha=0.35)
    stroke_lines(c, [pp([to_map(la, lo, geo) for la, lo in w]) for w in d["park"]], (20, 110, 60), 0.7, dash=(5, 1.5, 1, 1.5))

    # Water.
    styles = {"river": 1.25, "stream": 0.65, "brook": 0.42, "seasonal": 0.35}
    for cls, wdt in styles.items():
        ls = [pp(l["points"]) for l in d["water"] if l["class"] == cls]
        stroke_lines(c, ls, BLUE_LINE, wdt, dash=(2, 1.2) if cls == "seasonal" else None)
    for poly in d["ponds"]:
        c.setStrokeColor(rgb(BLUE_LINE))
        c.setLineWidth(0.35)
        c.drawPath(polyline(c, pp(poly), True), stroke=1, fill=0)

    # Roads: casings first, then fills, minor to major.
    road_style = [  # (highways, casing colour, casing width, fill colour, fill width)
        ({"track"}, None, 0, (150, 100, 60), 0.8),
        ({"residential", "service", "living_street"}, (110, 110, 110), 1.6, (255, 255, 255), 1.0),
        ({"unclassified", "tertiary", "secondary", "tertiary_link", "secondary_link"}, (90, 60, 40), 2.4, (250, 196, 70), 1.7),
        ({"trunk", "primary", "trunk_link", "primary_link"}, (70, 30, 20), 3.2, (236, 96, 44), 2.4),
    ]
    roads = [l for l in d["roads"] if l["group"] != "trails"]
    for hw, cas, cw, fill, fw in road_style:
        ls = [pp(l["points"]) for l in roads if l["highway"] in hw]
        if cas:
            stroke_lines(c, ls, cas, cw)
    for hw, cas, cw, fill, fw in road_style:
        ls = [pp(l["points"]) for l in roads if l["highway"] in hw]
        stroke_lines(c, ls, fill, fw, dash=(3, 1.6) if not cas else None, cap=0 if not cas else 1)
    # Bridges: black brackets either side.
    for l in d["roads"]:
        if not l.get("bridge"):
            continue
        pts = pp(l["points"])
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        ln = math.hypot(x1 - x0, y1 - y0)
        if ln < 0.5:
            continue
        nx, ny = -(y1 - y0) / ln, (x1 - x0) / ln
        off = 2.2 if l["group"] != "trails" else 1.4
        c.setStrokeColor(rgb((0, 0, 0)))
        c.setLineWidth(0.5)
        for sgn in (1, -1):
            c.line(x0 + nx * off * sgn, y0 + ny * off * sgn, x1 + nx * off * sgn, y1 + ny * off * sgn)

    # Trails: coloured by trail, unnamed paths thin black.
    trails = [l for l in d["roads"] if l["group"] == "trails"]
    by_colour = {}
    for l in trails:
        key = trail_colour(l["name"]) if l.get("name") else None
        by_colour.setdefault(key, []).append(pp(l["points"]))
    for key, ls in by_colour.items():
        if key is None:
            stroke_lines(c, ls, (30, 30, 30), 0.45, dash=(1.6, 1.0))
        else:
            stroke_lines(c, ls, (255, 255, 255), 1.5, alpha=0.6)
            stroke_lines(c, ls, key, 0.95, dash=(3.2, 1.3), cap=0)

    # Aerial lifts and the SkyBridge.
    for name, pts in d["aerial"]:
        q = pp(pts)
        stroke_lines(c, [q], (20, 20, 20), 0.7)
        (x0, y0), (x1, y1) = q[0], q[-1]
        ln = math.hypot(x1 - x0, y1 - y0)
        nx, ny = -(y1 - y0) / ln * 1.6, (x1 - x0) / ln * 1.6
        for k in range(int(ln / 6) + 1):
            t = k * 6 / ln
            cx, cy = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            c.line(cx - nx, cy - ny, cx + nx, cy + ny)
    if "skybridge" in d:
        q = pp(d["skybridge"])
        stroke_lines(c, [q], (0, 0, 0), 2.0)
        stroke_lines(c, [q], (255, 255, 255), 0.9)

    # Buildings.
    c.setFillColor(rgb((70, 64, 62)))
    p = c.beginPath()
    for tpl, x, z, corners in d["buildings"]:
        q = pp(corners)
        p.moveTo(*q[0])
        for v in q[1:]:
            p.lineTo(*v)
        p.close()
    c.drawPath(p, stroke=0, fill=1)

    # Grid.
    c.setStrokeColor(rgb(GRID, 0.85))
    c.setLineWidth(0.6)
    for k in range(1, 21):
        x, _ = P(k * 1000.0, 0)
        c.line(x, MY0, x, MY0 + MAP_W)
        _, y = P(0, SIZE - k * 1000.0)
        c.line(MX0, y, MX0 + MAP_W, y)

    # Symbols and names, most important first.
    places = d["places"]
    elev = d["elev"]

    def height(x, z, r=40.0):
        i, j = int(z / 5), int(x / 5)
        k = int(r / 5)
        return float(elev[max(0, i - k):i + k + 1, max(0, j - k):j + k + 1].max())

    def reserve(x, y, s=3.0):
        L.take((x - s, y - s, x + s, y + s))

    bxz = np.array([(x, z) for _, x, z, _ in d["buildings"]])

    def town_anchor(x, z, reach):
        """The middle of the densest knot of buildings near a place's node (OSM nodes sit off-centre)."""
        pts = bxz[np.hypot(bxz[:, 0] - x, bxz[:, 1] - z) < reach]
        if len(pts) < 6:
            return x, z
        dens = [(np.hypot(pts[:, 0] - a, pts[:, 1] - b) < 200).sum() for a, b in pts]
        k = int(np.argmax(dens))
        return tuple(pts[np.hypot(pts[:, 0] - pts[k, 0], pts[:, 1] - pts[k, 1]) < 250].mean(0))

    towns = [p for p in places if p["kind"] in ("place=city", "place=town", "place=village", "place=hamlet")]
    seen = set()
    for p in sorted(towns, key=lambda p: ["place=city", "place=town", "place=village", "place=hamlet"].index(p["kind"])):
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        ax, az = town_anchor(p["x"], p["z"], 3500.0 if p["kind"] in ("place=city", "place=town") else 600.0)
        x, y = P(ax, az)
        big = p["name"] == "Gatlinburg"
        font, size = ("NB", 16) if big else (("NB", 11) if p["kind"] == "place=town" else ("NB", 8.5))
        s = p["name"].upper() if big else p["name"]
        label(c, L, x, y, s, font, size, (10, 10, 10), offsets=((0, 1), (1, 0), (-1, 0), (0, -1)), gap=0,
              halo_w=2.2)

    peaks = {}
    for p in places:
        if p["kind"] == "natural=peak":
            h = height(p["x"], p["z"])
            key = p["name"]
            if key in peaks and any(math.hypot(p["x"] - q[0], p["z"] - q[1]) < 1500 for q in peaks[key]):
                continue
            peaks.setdefault(key, []).append((p["x"], p["z"], h))
    plist = sorted(((n, x, z, h) for n, v in peaks.items() for x, z, h in v), key=lambda t: -t[3])
    done = []
    for name, x, z, h in plist:
        if any(math.hypot(x - a, z - b) < 200 for a, b in done):       # one name per summit
            continue
        done.append((x, z))
        px_, py_ = P(x, z)
        sym_peak(c, px_, py_, 5.2)
        if label(c, L, px_, py_ + 1.2, name, "NBI", 7.2, (60, 35, 20), offsets=((1, 0), (-1, 0), (0, 1), (0, -1)),
                 gap=3.4):
            label(c, L, px_, py_ - 3.8, "%d" % round(h), "N", 6.0, (60, 35, 20), offsets=((1, 0), (-1, 0), (0, -1)),
                  gap=3.4)
        reserve(px_, py_, 2.6)

    for p in places:
        if p["kind"] == "natural=saddle" and p["name"]:
            px_, py_ = P(p["x"], p["z"])
            label(c, L, px_, py_, p["name"], "NI", 6.0, (70, 50, 40), offsets=((0, 1), (0, -1), (1, 0), (-1, 0)), gap=1)

    for name, x, z in d["falls"]:
        px_, py_ = P(x, z)
        sym_fall(c, px_, py_, 5.6)
        label(c, L, px_, py_, name, "NI", 6.4, (20, 90, 180), gap=3.6)
        reserve(px_, py_, 2.8)

    symbol_for = {"tourism=camp_site": sym_tent, "tourism=alpine_hut": sym_hut, "amenity=shelter": sym_hut,
                  "tourism=viewpoint": sym_view, "highway=trailhead": sym_signpost,
                  "amenity=ranger_station": sym_ranger, "tourism=picnic_site": None}
    for p in places:
        f = symbol_for.get(p["kind"])
        if f is None:
            continue
        px_, py_ = P(p["x"], p["z"])
        if not L.free((px_ - 2, py_ - 2, px_ + 2, py_ + 2)) and p["kind"] == "tourism=viewpoint":
            continue
        f(c, px_, py_, 5.8)
        if p["name"] and p["kind"] != "highway=trailhead":
            nm = p["name"].replace("Campground", "Cg.")
            label(c, L, px_, py_, nm, "N", 6.2, (20, 20, 20), gap=3.8)
        reserve(px_, py_, 3.0)

    for p in places:
        if p["kind"].startswith("historic=") and p["name"]:
            px_, py_ = P(p["x"], p["z"])
            sym_historic(c, px_, py_, 5.0)
            label(c, L, px_, py_, p["name"], "NI", 6.0, (150, 30, 50), gap=3.4)
            reserve(px_, py_, 2.6)

    kinds = {"church": (sym_cross, ("church", "chapel")),
             "police": (sym_police, ("city_policestation", "village_policestation")),
             "fire": (sym_fire, ("city_firestation",)),
             "medic": (sym_firstaid, ("village_healthcare", "city_hospital")),
             "fuel": (sym_fuel, ("fuelstation_build",))}
    for f, prefixes in kinds.values():
        for tpl, x, z, corners in d["buildings"]:
            if tpl.startswith(prefixes):
                px_, py_ = P(x, z)
                b = (px_ - 3.0, py_ + 2.2, px_ + 3.0, py_ + 8.4)
                if L.free(b):
                    f(c, px_, py_ + 5.3, 5.4)
                    L.take(b)

    # Parking outside town (trailheads and overlooks).
    for p in places:
        if p["kind"] == "amenity=parking":
            if np.min(np.hypot(bxz[:, 0] - p["x"], bxz[:, 1] - p["z"])) < 300:
                continue
            px_, py_ = P(p["x"], p["z"])
            b = (px_ - 2.9, py_ - 2.9, px_ + 2.9, py_ + 2.9)
            if L.free(b):
                sym_parking(c, px_, py_, 5.2)
                L.take(b)

    # The SkyBridge and the lifts by name.
    if "skybridge" in d:
        (x0, z0), (x1, z1) = d["skybridge"][0], d["skybridge"][-1]
        px_, py_ = P((x0 + x1) / 2, (z0 + z1) / 2)
        label(c, L, px_, py_, "Gatlinburg SkyBridge", "NBI", 6.0, (20, 20, 20), offsets=((0, -1), (0, 1)), gap=2)
    for name, pts in d["aerial"]:
        if name:
            (x0, z0), (x1, z1) = pts[0], pts[-1]
            px_, py_ = P((x0 + x1) / 2, (z0 + z1) / 2)
            label(c, L, px_, py_, name, "NI", 5.6, (20, 20, 20))

    # Stream and river names along their longest line.
    best = {}
    for l in d["water"]:
        if not l.get("name"):
            continue
        q = l["points"]
        ln = sum(math.hypot(q[i + 1][0] - q[i][0], q[i + 1][1] - q[i][1]) for i in range(len(q) - 1))
        if ln > best.get(l["name"], (0, None))[0]:
            best[l["name"]] = (ln, q)
    for name, (ln, q) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        if ln < 900:
            continue
        place_along(c, L, q, name, "NI", 6.2 if ln > 3000 else 5.6, (20, 90, 180), ln)

    # A few major trails by name.
    tbest = {}
    for l in trails:
        if l.get("name"):
            q = l["points"]
            ln = sum(math.hypot(q[i + 1][0] - q[i][0], q[i + 1][1] - q[i][1]) for i in range(len(q) - 1))
            if ln > tbest.get(l["name"], (0, None))[0]:
                tbest[l["name"]] = (ln, q)
    for name, (ln, q) in sorted(tbest.items(), key=lambda kv: -kv[1][0]):
        if ln > 1500 and "Horse" not in name and "Quiet Walkway" not in name:
            place_along(c, L, q, name, "NBI", 5.4, (120, 30, 30), ln, offset=3.0)

    # Contour heights on the index contours, tops uphill.
    elev_s = d["elev_smooth"]
    rng = np.random.default_rng(7)
    placed = []
    for gz in np.arange(400.0, SIZE - 300, 650.0):
        for gx in np.arange(400.0, SIZE - 300, 650.0):
            x, z = gx + rng.uniform(-200, 200), gz + rng.uniform(-200, 200)
            pt = to_index_contour(elev_s, x, z)
            if pt is None:
                continue
            x, z, lev, ux, uz = pt
            if any(math.hypot(x - a, z - b) < 900 for a, b in placed):
                continue
            px_, py_ = P(x, z)
            s = "%d" % lev
            w = pdfmetrics.stringWidth(s, "N", 4.8)
            ang = math.degrees(math.atan2(-ux, uz))
            b = (px_ - w / 2 - 1, py_ - w / 2 - 1, px_ + w / 2 + 1, py_ + w / 2 + 1)
            if not L.free(b):
                continue
            L.take(b)
            placed.append((x, z))
            text(c, px_, py_, s, "N", 4.8, (150, 85, 40), anchor="c", angle=ang, halo=(240, 236, 220), halo_w=1.6,
                 halo_a=0.9)
    c.restoreState()

    # Frame and grid labels.
    c.setStrokeColor(rgb((0, 0, 0)))
    c.setLineWidth(1.2)
    c.rect(MX0, MY0, MAP_W, MAP_W, stroke=1, fill=0)
    c.setFillColor(rgb(GRID))
    for k in range(21):
        xc = (k * 1000.0 + min((k + 1) * 1000.0, SIZE)) / 2
        x, _ = P(xc, 0)
        c.setFont("NB", 9)
        c.drawCentredString(x, MY0 + MAP_W + 3.5, "%02d" % k)
        c.drawCentredString(x, MY0 - 10.5, "%02d" % k)
        zc = SIZE - (k * 1000.0 + min((k + 1) * 1000.0, SIZE)) / 2
        _, y = P(0, zc)
        c.drawCentredString(MX0 - 7, y - 3, "%02d" % k)
        c.drawCentredString(MX0 + MAP_W + 7, y - 3, "%02d" % k)
    scale_bar(c, MX0 + MAP_W - 88 * MM, MY0 + 9 * MM)


def to_index_contour(elev, x, z):
    """Walk from (x, z) to the nearest 100 m contour; return the point, level and uphill unit vector."""
    cell = SIZE / elev.shape[0]

    def sample(x, z):
        u, v = x / cell, z / cell
        j, i = int(u), int(v)
        if not (1 <= i < elev.shape[0] - 2 and 1 <= j < elev.shape[1] - 2):
            return None
        fu, fv = u - j, v - i
        h = (elev[i, j] * (1 - fu) * (1 - fv) + elev[i, j + 1] * fu * (1 - fv)
             + elev[i + 1, j] * (1 - fu) * fv + elev[i + 1, j + 1] * fu * fv)
        gx = (elev[i, j + 1] - elev[i, j - 1]) / (2 * cell)
        gz = (elev[i + 1, j] - elev[i - 1, j]) / (2 * cell)
        return float(h), float(gx), float(gz)
    s = sample(x, z)
    if s is None:
        return None
    lev = round(s[0] / INDEX) * INDEX
    for _ in range(8):
        h, gx, gz = s
        g2 = gx * gx + gz * gz
        if g2 < 0.01:
            return None
        step = (h - lev) / g2
        x, z = x - step * gx, z - step * gz
        s = sample(x, z)
        if s is None:
            return None
    h, gx, gz = s
    g = math.hypot(gx, gz)
    if abs(h - lev) > 1.0 or not (0.12 < g < 0.9):
        return None
    return x, z, int(lev), gx / g, gz / g


def place_along(c, L, q, name, font, size, colour, ln, offset=0.0):
    """Name along a line near its middle, kept upright."""
    w_pt = pdfmetrics.stringWidth(name, font, size)
    w_m = w_pt / MAP_W * SIZE
    if w_m > ln * 0.8:
        return False
    cum = [0.0]
    for i in range(len(q) - 1):
        cum.append(cum[-1] + math.hypot(q[i + 1][0] - q[i][0], q[i + 1][1] - q[i][1]))
    for frac in (0.5, 0.35, 0.65, 0.2, 0.8):
        a, b = frac * ln - w_m / 2, frac * ln + w_m / 2
        if a < 0 or b > ln:
            continue
        pa, pb = point_at(q, cum, a), point_at(q, cum, b)
        mid = point_at(q, cum, frac * ln)
        dx, dz = pb[0] - pa[0], pb[1] - pa[1]
        if math.hypot(dx, dz) < w_m * 0.8:                  # too bendy here
            continue
        ang = math.degrees(math.atan2(dz, dx))
        if ang > 90:
            ang -= 180
        elif ang < -90:
            ang += 180
        x, y = P(*mid)
        nrm = math.radians(ang + 90)
        x += math.cos(nrm) * (size * 0.3 + offset)
        y += math.sin(nrm) * (size * 0.3 + offset)
        r = w_pt / 2 + 1
        hh = size * 0.6
        b_ = (x - abs(math.cos(math.radians(ang))) * r - hh, y - abs(math.sin(math.radians(ang))) * r - hh,
              x + abs(math.cos(math.radians(ang))) * r + hh, y + abs(math.sin(math.radians(ang))) * r + hh)
        if L.free(b_):
            L.take(b_)
            text(c, x, y - size * 0.3, name, font, size, colour, anchor="c", angle=ang)
            return True
    return False


def point_at(q, cum, s):
    for i in range(len(q) - 1):
        if cum[i + 1] >= s:
            t = (s - cum[i]) / max(cum[i + 1] - cum[i], 1e-9)
            return q[i][0] + (q[i + 1][0] - q[i][0]) * t, q[i][1] + (q[i + 1][1] - q[i][1]) * t
    return q[-1]


def scale_bar(c, x, y):
    c.setFillColor(rgb((255, 255, 255), 0.88))
    c.setStrokeColor(rgb((0, 0, 0)))
    c.setLineWidth(0.4)
    c.rect(x - 4 * MM, y - 5 * MM, 86 * MM, 16 * MM, stroke=1, fill=1)
    km = MAP_W / SIZE * 1000
    marks = [0, 0.5, 1, 2]
    for i in range(len(marks) - 1):
        c.setFillColor(rgb((0, 0, 0) if i % 2 == 0 else (255, 255, 255)))
        c.rect(x + marks[i] * km, y, (marks[i + 1] - marks[i]) * km, 1.6 * MM, stroke=1, fill=1)
    c.setFillColor(rgb((0, 0, 0)))
    c.setFont("N", 7)
    for m in marks:
        c.drawCentredString(x + m * km, y + 2.6 * MM, ("%g" % m).replace(".", ","))
    c.drawString(x + 2 * km + 4, y + 0.2 * MM, "km")
    c.drawString(x, y - 3.4 * MM, "1:36 000   Grid 1 km   Contours 20 m, bold every 100 m")
    nx = x + 2 * km + 16 * MM
    c.drawPath(polyline(c, [(nx, y + 7 * MM), (nx - 2.2 * MM, y), (nx, y + 1.5 * MM), (nx + 2.2 * MM, y)], True),
               stroke=0, fill=1)
    c.setFont("AB", 9)
    c.drawCentredString(nx, y - 3.4 * MM, "N")


def sidebar(c, d, cover_jpg):
    x0, x1 = SX0, SX1
    w = x1 - x0
    top = PAGE_H - 8 * MM
    # Legend.
    rows = [
        ("CONTOURS (INTERVAL 20 m, 100 m)", "contours"), ("MAIN PAVED ROAD", "main"), ("PAVED ROAD", "paved"),
        ("STREET", "street"), ("UNPAVED ROAD", "track"), ("BRIDGE", "bridge"),
        ("HIKING TRAIL (BY TRAIL), FOOTPATH", "trail"), ("APPALACHIAN TRAIL", "at"),
        ("CABLEWAY, CHAIRLIFT, SKYBRIDGE", "lift"), ("NATIONAL PARK BOUNDARY", "park"),
        ("URBANIZED AREA, BUILDING, FOREST", "urban"), ("WATER, STREAM, RIVER", "water"), ("WATERFALL", "fall"),
        ("PEAK, HEIGHT", "peak"), ("CLIFF, ROCK", "rock"), ("CHURCH", "church"),
        ("FIRST AID, POLICE, FIRE STATION", "services"), ("FUEL STATION", "fuel"), ("CAMPSITE, SHELTER", "camp"),
        ("RANGER STATION", "ranger"), ("VIEWPOINT", "view"), ("TRAILHEAD, PARKING", "trailhead"),
        ("HISTORIC SITE", "historic"), ("GRID 1 km", "grid")]
    row_h, head_h, leg_h = LEG_ROW_H, LEG_HEAD, LEG_H
    assert len(rows) == LEG_ROWS
    c.setFillColor(rgb((255, 255, 255)))
    c.setStrokeColor(rgb((60, 60, 60)))
    c.setLineWidth(0.5)
    c.rect(x0, top - leg_h, w, leg_h, stroke=1, fill=1)
    c.setFillColor(rgb(GREEN_PANEL))
    c.rect(x0, top - head_h, w, head_h, stroke=0, fill=1)
    c.setFillColor(rgb((255, 255, 255)))
    c.setFont("NB", 15)
    c.drawRightString(x1 - 4 * MM, top - head_h + 2.3 * MM, "LEGEND")
    y = top - head_h - 6 * MM
    c.setFillColor(rgb((20, 20, 20)))
    c.setFont("N", 9)
    c.drawString(x0 + 4 * MM, y, "NAMES")
    sx = x0 + w * 0.40
    for s, f, size in (("GATLINBURG", "NB", 11), ("Town", "NB", 9), ("Village", "NB", 7.5), ("Peak", "NBI", 7),
                       ("Gap", "NI", 6.5), ("Creek", "NI", 6.5)):
        c.setFont(f, size)
        c.setFillColor(rgb((20, 90, 180) if s == "Creek" else ((60, 35, 20) if s in ("Peak", "Gap") else (10, 10, 10))))
        c.drawString(sx, y, s)
        sx += pdfmetrics.stringWidth(s, f, size) + 3.2 * MM
    y -= 3 * MM
    for name, kind in rows:
        y -= row_h
        c.setStrokeColor(rgb((215, 215, 215)))
        c.setLineWidth(0.3)
        c.line(x0 + 3 * MM, y - 2.2 * MM, x1 - 3 * MM, y - 2.2 * MM)
        c.setFillColor(rgb((20, 20, 20)))
        c.setFont("N", 9)
        c.drawString(x0 + 4 * MM, y, name)
        c.saveState()
        c.translate(x0 + w * 0.58, y + 1.1 * MM)
        c.scale(1.45, 1.45)
        legend_symbol(c, kind, 0, 0, w * 0.36 / 1.45)
        c.restoreState()
    # Locator inset.
    inset_top = top - leg_h - 4 * MM
    inset(c, d, x0, inset_top - INSET_H, w, INSET_H)
    # Title panel: the rendered view with the title over its foot.
    p_top, p_bot = PANEL_TOP, PANEL_BOT
    c.setFillColor(rgb(GREEN_PANEL))
    c.rect(x0, p_bot, w, p_top - p_bot, stroke=0, fill=1)
    img_y = COVER_Y
    c.drawImage(cover_jpg, x0, img_y, w, COVER_H)
    size = min(0.92 * w / pdfmetrics.stringWidth(s, "T", 1) for s in ("GREAT SMOKY", "MOUNTAINS"))
    c.setFillColor(rgb((0, 0, 0), 0.30))
    c.rect(x0, img_y, w, size * 1.85, stroke=0, fill=1)
    text(c, x0 + w / 2, img_y + size * 0.95, "GREAT SMOKY", "T", size, (255, 255, 255), anchor="c",
         halo=(20, 40, 30), halo_w=2.5, halo_a=0.6)
    text(c, x0 + w / 2, img_y + size * 0.12, "MOUNTAINS", "T", size, (255, 255, 255), anchor="c",
         halo=(20, 40, 30), halo_w=2.5, halo_a=0.6)
    # Banners and edition.
    by = p_bot + 17 * MM
    c.setFillColor(rgb((255, 255, 255)))
    c.rect(x0 + 4 * MM, by, w * 0.55, 9 * MM, stroke=0, fill=1)
    c.setFillColor(rgb(GREEN_PANEL))
    c.setFont("NB", 12)
    c.drawCentredString(x0 + 4 * MM + w * 0.275, by + 2.8 * MM, "GATLINBURG & MT. LE CONTE")
    c.setFillColor(rgb(RED))
    c.rect(x0 + 6 * MM + w * 0.55, by, w * 0.45 - 10 * MM, 9 * MM, stroke=0, fill=1)
    c.setFillColor(rgb((255, 255, 255)))
    c.drawCentredString(x0 + 6 * MM + w * 0.55 + (w * 0.45 - 10 * MM) / 2, by + 2.8 * MM, "HIKING TRAILS")
    c.setFont("NB", 17)
    c.drawString(x0 + 4 * MM, p_bot + 5 * MM, "TOPOGRAPHIC MAP")
    c.drawRightString(x1 - 4 * MM, p_bot + 5 * MM, "1:36 000")
    ey = p_top - 12 * MM
    c.setFillColor(rgb((255, 255, 255)))
    c.rect(x1 - 62 * MM, ey, 30 * MM, 8 * MM, stroke=0, fill=1)
    c.setFillColor(rgb(RED))
    c.rect(x1 - 32 * MM, ey, 28 * MM, 8 * MM, stroke=0, fill=1)
    c.setFont("NB", 11)
    c.setFillColor(rgb(GREEN_PANEL))
    c.drawCentredString(x1 - 47 * MM, ey + 2.4 * MM, "1ST EDITION")
    c.setFillColor(rgb((255, 255, 255)))
    c.drawCentredString(x1 - 18 * MM, ey + 2.4 * MM, "2026")
    c.setFont("N", 6.5)
    lines = ["A DayZ terrain by PackJC, drawn from the terrain's own heights and placed objects.",
             "Roads, trails, water, places and buildings (c) OpenStreetMap contributors, ODbL.",
             "A game map: not for real-world navigation."]
    for i, s in enumerate(lines):
        c.drawString(x0 + 4 * MM, p_top - 6 * MM - i * 3 * MM, s.replace("(c)", "\u00a9"))


def legend_symbol(c, kind, x, y, w):
    def seg(colour, width, dash=None, cap=1):
        stroke_lines(c, [[(x, y), (x + w * 0.45, y)]], colour, width, dash=dash, cap=cap)
    if kind == "contours":
        stroke_lines(c, [[(x, y + 1.5), (x + w * 0.45, y + 1.5)]], CONTOUR_RGB, 0.45)
        stroke_lines(c, [[(x, y - 1.5), (x + w * 0.45, y - 1.5)]], CONTOUR_RGB, 1.0)
    elif kind == "main":
        seg((70, 30, 20), 3.2)
        seg((236, 96, 44), 2.4)
    elif kind == "paved":
        seg((90, 60, 40), 2.4)
        seg((250, 196, 70), 1.7)
    elif kind == "street":
        seg((110, 110, 110), 1.6)
        seg((255, 255, 255), 1.0)
    elif kind == "track":
        seg((150, 100, 60), 0.8, dash=(3, 1.6), cap=0)
    elif kind == "bridge":
        seg((90, 60, 40), 2.4)
        seg((250, 196, 70), 1.7)
        c.setStrokeColor(rgb((0, 0, 0)))
        c.setLineWidth(0.5)
        c.line(x + w * 0.12, y + 2.2, x + w * 0.33, y + 2.2)
        c.line(x + w * 0.12, y - 2.2, x + w * 0.33, y - 2.2)
    elif kind == "trail":
        for i, col in enumerate(TRAIL_COLOURS[1:]):
            stroke_lines(c, [[(x + i * w * 0.17, y), (x + i * w * 0.17 + w * 0.14, y)]], col, 0.95, dash=(3.2, 1.3), cap=0)
        stroke_lines(c, [[(x + w * 0.55, y), (x + w * 0.85, y)]], (30, 30, 30), 0.45, dash=(1.6, 1.0))
    elif kind == "at":
        seg(RED, 0.95, dash=(3.2, 1.3), cap=0)
    elif kind == "lift":
        seg((20, 20, 20), 0.7)
        for k in range(5):
            c.line(x + k * w * 0.1, y - 1.6, x + k * w * 0.1, y + 1.6)
        stroke_lines(c, [[(x + w * 0.6, y), (x + w * 0.9, y)]], (0, 0, 0), 2.0)
        stroke_lines(c, [[(x + w * 0.6, y), (x + w * 0.9, y)]], (255, 255, 255), 0.9)
    elif kind == "park":
        stroke_lines(c, [[(x, y), (x + w * 0.45, y)]], (20, 110, 60), 2.2, alpha=0.35)
        seg((20, 110, 60), 0.7, dash=(5, 1.5, 1, 1.5))
    elif kind == "urban":
        c.setFillColor(rgb(URBAN))
        c.rect(x, y - 2.5, w * 0.2, 5, stroke=0, fill=1)
        c.setFillColor(rgb((70, 64, 62)))
        c.rect(x + w * 0.27, y - 1.5, w * 0.06, 3.5, stroke=0, fill=1)
        c.setFillColor(rgb(FOREST))
        c.rect(x + w * 0.4, y - 2.5, w * 0.2, 5, stroke=0, fill=1)
    elif kind == "water":
        c.setFillColor(rgb(WATER))
        c.rect(x, y - 2.5, w * 0.16, 5, stroke=0, fill=1)
        stroke_lines(c, [[(x + w * 0.22, y), (x + w * 0.42, y)]], BLUE_LINE, 0.55)
        stroke_lines(c, [[(x + w * 0.5, y), (x + w * 0.72, y)]], BLUE_LINE, 1.25)
    elif kind == "fall":
        sym_fall(c, x + 4, y, 4.5)
    elif kind == "peak":
        sym_peak(c, x + 4, y)
        c.setFillColor(rgb((60, 35, 20)))
        c.setFont("N", 6)
        c.drawString(x + 9, y - 2, "2010")
    elif kind == "rock":
        c.setFillColor(rgb(ROCK_RGB))
        for k in range(4):
            cx = x + 3 + k * 5
            c.drawPath(polyline(c, [(cx - 1.8, y - 1.2), (cx + 1.8, y - 1.2), (cx, y + 1.8)], True), stroke=0, fill=1)
    elif kind == "church":
        sym_cross(c, x + 4, y, 4.6)
    elif kind == "services":
        sym_firstaid(c, x + 4, y, 4.4)
        sym_police(c, x + 12, y, 4.4)
        sym_fire(c, x + 20, y, 4.4)
    elif kind == "fuel":
        sym_fuel(c, x + 4, y, 4.4)
    elif kind == "camp":
        sym_tent(c, x + 4, y, 4.6)
        sym_hut(c, x + 13, y, 4.6)
    elif kind == "ranger":
        sym_ranger(c, x + 4, y, 4.6)
    elif kind == "view":
        sym_view(c, x + 4, y, 4.6)
    elif kind == "trailhead":
        sym_signpost(c, x + 4, y, 4.6)
        sym_parking(c, x + 13, y, 4.4)
    elif kind == "historic":
        sym_historic(c, x + 4, y, 4.2)
    elif kind == "grid":
        stroke_lines(c, [[(x, y), (x + w * 0.45, y)]], GRID, 0.6)
        c.setFillColor(rgb(GRID))
        c.setFont("NB", 8)
        c.drawString(x + w * 0.5, y - 2.5, "07")


def inset(c, d, x, y, w, h):
    c.setFillColor(rgb((248, 246, 238)))
    c.setStrokeColor(rgb((60, 60, 60)))
    c.setLineWidth(0.5)
    c.rect(x, y, w, h, stroke=1, fill=1)
    rings = [[utm(la, lo, 17) for la, lo in way] for way in d["park"]]
    allp = np.array([p for r in rings for p in r])
    e0, n0 = allp.min(0) - 6000
    e1, n1 = allp.max(0) + 6000
    s = min(w / (e1 - e0), h / (n1 - n0))
    ox, oy = x + (w - (e1 - e0) * s) / 2, y + (h - (n1 - n0) * s) / 2

    def q(e, n):
        return ox + (e - e0) * s, oy + (n - n0) * s
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, y, w, h)
    c.clipPath(clip, stroke=0, fill=0)
    for ring in join_rings(rings):
        c.setFillColor(rgb((182, 216, 150)))
        c.setStrokeColor(rgb((20, 110, 60)))
        c.setLineWidth(0.6)
        c.drawPath(polyline(c, [q(*p) for p in ring], True), stroke=1, fill=1)
    geo = d["geo"]
    e_a, n_a = -geo["offset_x"], -geo["offset_y"]
    fx0, fy0 = q(e_a, n_a)
    fx1, fy1 = q(e_a + SIZE, n_a + SIZE)
    c.setStrokeColor(rgb(RED))
    c.setLineWidth(1.3)
    c.rect(fx0, fy0, fx1 - fx0, fy1 - fy0, stroke=1, fill=0)
    for name, la, lo in d["towns_inset"]:
        tx, ty = q(*utm(la, lo, 17))
        if not (x + 3 < tx < x + w - 3 and y + 3 < ty < y + h - 3):
            continue
        c.setFillColor(rgb((20, 20, 20)))
        c.circle(tx, ty, 1.3, stroke=0, fill=1)
        text(c, tx + 2.5, ty - 2, name, "N", 6.5, (20, 20, 20), halo_w=1.2)
    text(c, x + w * 0.30, y + h * 0.80, "TENNESSEE", "NB", 9, (90, 90, 90), anchor="c", halo=None)
    text(c, x + w * 0.70, y + h * 0.16, "NORTH CAROLINA", "NB", 9, (90, 90, 90), anchor="c", halo=None)
    text(c, x + w * 0.66, y + h * 0.40, "Great Smoky Mountains National Park", "NBI", 7.5, (20, 90, 50), anchor="c",
         halo_w=1.2)
    km = 10000 * s
    c.setStrokeColor(rgb((0, 0, 0)))
    c.setLineWidth(1)
    c.line(x + 4 * MM, y + 4 * MM, x + 4 * MM + km, y + 4 * MM)
    c.setFillColor(rgb((0, 0, 0)))
    c.setFont("N", 6)
    c.drawString(x + 4 * MM, y + 5.2 * MM, "0")
    c.drawString(x + 4 * MM + km - 6, y + 5.2 * MM, "10 km")
    c.restoreState()
    c.setFillColor(rgb(RED))
    c.setFont("NB", 7)
    c.drawString(fx1 + 2, fy1 - 6, "this map")


def join_rings(ways):
    """Join boundary ways into closed rings by their end points."""
    ways = [list(w) for w in ways if len(w) > 1]
    rings = []
    while ways:
        ring = ways.pop(0)
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for i, w in enumerate(ways):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[::-1][1:]
                elif w[-1] == ring[0]:
                    ring = w[:-1] + ring
                elif w[0] == ring[0]:
                    ring = w[::-1][:-1] + ring
                else:
                    continue
                ways.pop(i)
                changed = True
                break
        rings.append(ring)
    return rings


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    register_fonts()
    d = load()
    relief_jpg = os.path.join(out, "relief.jpg")
    cover_jpg = os.path.join(out, "cover.jpg")
    relief(d, relief_jpg)
    cover(cover_jpg, 2400, int(2400 * COVER_H / (SX1 - SX0)))
    print("cover rendered", flush=True)
    pdf = os.path.join(out, "GreatSmokyMountains_Map.pdf")
    c = canvas.Canvas(pdf, pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    c.setTitle("Great Smoky Mountains - Topographic Map 1:36 000")
    c.setAuthor("PackJC")
    c.setSubject("DayZ terrain map: Gatlinburg and Mt. Le Conte")
    c.setFillColor(rgb((255, 255, 255)))
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    draw_map(c, d, relief_jpg)
    sidebar(c, d, cover_jpg)
    c.showPage()
    c.save()
    print("wrote %s (%.1f MB)" % (pdf, os.path.getsize(pdf) / 1e6))


if __name__ == "__main__":
    main()
