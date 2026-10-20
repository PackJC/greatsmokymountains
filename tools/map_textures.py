"""Draw the paper map item's three textures for this terrain, in the layout of the
vanilla map model (DZ\\gear\\navigation\\Map_chernarus_animated.p3d, which
ItemMap textures from the world config's mapTextureClosed / mapTextureOpened /
mapTextureLegend):

- map_unfolded_co (4096 x 4096): the opened sheet, a topographic map of the whole
  terrain like the printed map (tools/topo_map.py): relief, roads, trails,
  streams, buildings, names, the 1 km grid numbered 00-20 from the top left,
  a title band and a scale bar. The model's UVs use only the top 4096 x 3720
  (v up to 0.908) and show it about 6 % taller than wide, so the map frame is
  drawn 1.06 times wider than tall and looks square in game.
- map_legend_co (512 x 2048): the strip beside the map on the opened sheet (like
  the PDF's sidebar): legend, locator inset of the national park and the cover
  (Mt. Le Conte, GREAT SMOKY MOUNTAINS), within the left 453 px the model uses.
  Drawn with square pixels like the vanilla strips, though the model shows the
  strip about 1.3 times taller than the texture.
- map_folded_co (512 x 512): the folded map: front cover, back panel (legend
  excerpt and locator, upright when the map is turned over sideways, which is
  how the model maps it) and the four edge strips (layers of folded map), in
  the model's UV islands (FRONT, BACK, STRIPS below).

    python tools/map_textures.py [<png folder> <paa folder> <ImageToPAA.exe>]

Defaults: source/maptex, data and DayZ Tools' ImageToPAA. The PNGs stay in the
png folder (never packed); the .paa files go to the paa folder. Takes under a
minute; it reads map/relief.jpg and map/cover.jpg, so run tools/topo_map.py
first if those change.

The drawing is topo_map.py's own: Raster below is a stand-in for the ReportLab
canvas that paints the same calls into a PIL image, so draw_map, the symbols,
legend_symbol and inset draw here as on the PDF. For the texture the map is set
smaller in points (topo_map.MAP_W, for the duration of draw_map) so names,
symbols and lines come out about 1.6 times larger relative to the map and fewer
labels fit, and the scale bar is swapped for one laid out for that size.
"""

import math
import os
import subprocess
import sys
from contextlib import contextmanager

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfbase import pdfmetrics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import topo_map as tm  # noqa: E402
from geo import utm  # noqa: E402
from topo_map import GREEN_PANEL, MM, RED, box_blur, inset, legend_symbol, rgb, text  # noqa: E402

ROOT = tm.ROOT
I2P = r"G:\SteamLibrary\steamapps\common\DayZ Tools\Bin\ImageToPAA\ImageToPAA.exe"
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
PAPER = (247, 246, 240)
GREEN_DARK = (18, 74, 48)

# Unfolded sheet (final pixels). The model's UVs: u 0.002-0.997, v 0.000-0.908.
TEX = 4096
SHEET_H = 3720                         # v 0.908: the sheet ends here, paper below
ASPECT = 1.06                          # model texels are this much taller than wide
FRAME_Y0, FRAME_Y1 = 212, 3652         # map frame top and bottom
FRAME_H = FRAME_Y1 - FRAME_Y0
FRAME_W = round(FRAME_H * ASPECT)
FRAME_X0 = (TEX - FRAME_W) // 2
FRAME_X1 = FRAME_X0 + FRAME_W
BAND_Y0, BAND_Y1 = 26, 150             # title band
assert FRAME_Y1 + 50 < SHEET_H         # room for the bottom grid numbers
PX_PER_PT = 3.6                        # vertical pixels per point of type and line width
SS = 2                                 # drawn at twice the size, then reduced

# Legend strip (final pixels): the model uses u 0.004-0.886 (x 0-453), v 0-1.
STRIP_W, STRIP_H, STRIP_USED = 512, 2048, 453
STRIP_PX = 1.9                         # pixels per point

# Folded map: the vanilla UV islands (512 px, x0 y0 x1 y1, read from the model's LODs).
# Art fills each island's bounds plus a few pixels; the panels' outlines are worn and
# slanted, so type and the legend keep to the largest rectangle inside every LOD's island.
FRONT, FRONT_SAFE = (2.0, 4.8, 240.8, 333.2), (18.5, 13.5, 225.0, 325.0)     # front cover
BACK, BACK_SAFE = (271.2, 2.2, 503.8, 332.8), (294.0, 10.0, 499.0, 320.5)    # back panel
STRIPS = [(15.2, 344.0, 262.2, 357.2),  # top edge (faces +y)
          (4.8, 368.0, 275.5, 385.8),   # bottom edge
          (7.0, 392.8, 392.5, 408.5),   # left edge
          (14.8, 421.5, 391.0, 438.0)]  # right edge

LEGEND_ROWS = [
    ("CONTOURS 20 m, 100 m", "contours"), ("MAIN PAVED ROAD", "main"), ("PAVED ROAD", "paved"),
    ("STREET", "street"), ("UNPAVED ROAD", "track"), ("BRIDGE", "bridge"),
    ("HIKING TRAIL, FOOTPATH", "trail"), ("APPALACHIAN TRAIL", "at"),
    ("CABLEWAY, LIFT, SKYBRIDGE", "lift"), ("NATIONAL PARK BOUNDARY", "park"),
    ("TOWN, BUILDING, FOREST", "urban"), ("WATER, STREAM, RIVER", "water"), ("WATERFALL", "fall"),
    ("PEAK, HEIGHT", "peak"), ("CLIFF, ROCK", "rock"), ("CHURCH", "church"),
    ("FIRST AID, POLICE, FIRE", "services"), ("FUEL STATION", "fuel"), ("CAMPSITE, SHELTER", "camp"),
    ("RANGER STATION", "ranger"), ("VIEWPOINT", "view"), ("TRAILHEAD, PARKING", "trailhead"),
    ("HISTORIC SITE", "historic"), ("GRID 1 km", "grid")]
BACK_ROWS = ["main", "paved", "track", "trail", "at", "park", "water", "peak", "camp", "view", "trailhead"]


# ------------------------------------------------------------------ a raster canvas

class Path:
    """The parts of ReportLab's path object that topo_map uses (page points)."""

    def __init__(self):
        self.subs = []                          # [points, closed]

    def moveTo(self, x, y):
        self.subs.append([[(x, y)], False])

    def lineTo(self, x, y):
        if not self.subs:
            self.moveTo(x, y)
        else:
            self.subs[-1][0].append((x, y))

    def curveTo(self, x1, y1, x2, y2, x3, y3):
        x0, y0 = self.subs[-1][0][-1]
        for t in np.linspace(0, 1, 17)[1:]:
            a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
            self.lineTo(a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3)

    def close(self):
        if self.subs:
            self.subs[-1][1] = True

    def rect(self, x, y, w, h):
        self.moveTo(x, y)
        self.lineTo(x + w, y)
        self.lineTo(x + w, y + h)
        self.lineTo(x, y + h)
        self.close()


class TextObject:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.font = self.size = None
        self.mode = 0
        self.s = ""

    def setFont(self, name, size, leading=None):
        self.font, self.size = name, size

    def setTextRenderMode(self, mode):
        self.mode = mode

    def textOut(self, s):
        self.s += s


def _colour(c):
    return (round(c.red * 255), round(c.green * 255), round(c.blue * 255), float(getattr(c, "alpha", 1.0)))


def _dashes(pts, pattern, phase=0.0):
    """The 'on' pieces of a dash pattern along a device polyline (N x 2)."""
    seg = np.hypot(*np.diff(pts, axis=0).T)
    keep = np.r_[True, seg > 1e-6]
    pts = pts[keep]
    if len(pts) < 2:
        return []
    cum = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    total = cum[-1]
    out, s = [], -phase
    while s < total:
        for i, ln in enumerate(pattern):
            if i % 2 == 0:
                a, b = max(s, 0.0), min(s + ln, total)
                if b > a:
                    inner = cum[(cum > a) & (cum < b)]
                    ts = np.r_[a, inner, b]
                    out.append(np.c_[np.interp(ts, cum, pts[:, 0]), np.interp(ts, cum, pts[:, 1])])
            s += ln
            if s >= total:
                break
    return out


class Raster:
    """Paints the ReportLab canvas calls used by topo_map.py into a PIL RGB image.

    `m` maps page points to image pixels (a 2 x 3 affine, y flipped). Antialiasing
    comes from drawing at a multiple of the final size and reducing."""

    def __init__(self, size, bg, m):
        self.img = Image.new("RGB", size, bg)
        self.m = np.array(m, float).reshape(2, 3)
        self.fill, self.stroke = (0, 0, 0, 1.0), (0, 0, 0, 1.0)
        self.lw, self.cap, self.join, self.dash = 1.0, 0, 0, None
        self.font, self.size = "N", 10
        self.clip = (0, 0) + size
        self.stack = []
        self.fonts = {}
        self.images = {}

    # state
    def saveState(self):
        self.stack.append((self.m.copy(), self.fill, self.stroke, self.lw, self.cap, self.join, self.dash,
                           self.font, self.size, self.clip))

    def restoreState(self):
        (self.m, self.fill, self.stroke, self.lw, self.cap, self.join, self.dash, self.font, self.size,
         self.clip) = self.stack.pop()

    def _concat(self, a, b, c, d, e, f):
        m = self.m
        self.m = np.array([[m[0, 0] * a + m[0, 1] * b, m[0, 0] * c + m[0, 1] * d, m[0, 0] * e + m[0, 1] * f + m[0, 2]],
                           [m[1, 0] * a + m[1, 1] * b, m[1, 0] * c + m[1, 1] * d, m[1, 0] * e + m[1, 1] * f + m[1, 2]]])

    def translate(self, dx, dy):
        self._concat(1, 0, 0, 1, dx, dy)

    def rotate(self, deg):
        a = math.radians(deg)
        self._concat(math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)

    def scale(self, kx, ky=None):
        self._concat(kx, 0, 0, kx if ky is None else ky, 0, 0)

    def setFillColor(self, c):
        self.fill = _colour(c)

    def setStrokeColor(self, c):
        self.stroke = _colour(c)

    def setLineWidth(self, w):
        self.lw = w

    def setLineCap(self, cap):
        self.cap = cap

    def setLineJoin(self, join):
        self.join = join

    def setDash(self, array=(), phase=0):
        self.dash = (list(array), phase) if array else None

    def setFont(self, name, size, leading=None):
        self.font, self.size = name, size

    def setTitle(self, *a):
        pass

    setAuthor = setSubject = setTitle

    # geometry
    def _dev(self, pts):
        p = np.asarray(pts, float).reshape(-1, 2)
        return p @ self.m[:, :2].T + self.m[:, 2]

    def _unit(self):
        return math.sqrt(abs(np.linalg.det(self.m[:, :2])))

    def _paint(self, mask, x0, y0, colour):
        """Composite a coverage mask (L) placed at (x0, y0) in the clip, in a colour with alpha."""
        cx0, cy0, cx1, cy1 = self.clip
        a0, b0 = max(x0, cx0), max(y0, cy0)
        a1, b1 = min(x0 + mask.width, cx1), min(y0 + mask.height, cy1)
        if a1 <= a0 or b1 <= b0:
            return
        if (a0, b0, a1, b1) != (x0, y0, x0 + mask.width, y0 + mask.height):
            mask = mask.crop((a0 - x0, b0 - y0, a1 - x0, b1 - y0))
        if colour[3] < 0.999:
            mask = mask.point([round(i * colour[3]) for i in range(256)])
        self.img.paste(colour[:3], (a0, b0, a1, b1), mask)

    def _box(self, arrays, pad):
        allp = np.vstack(arrays)
        x0, y0 = np.floor(allp.min(0) - pad).astype(int)
        x1, y1 = np.ceil(allp.max(0) + pad).astype(int)
        cx0, cy0, cx1, cy1 = self.clip
        return max(x0, cx0), max(y0, cy0), min(x1, cx1), min(y1, cy1)

    def _fill_subs(self, subs):
        polys = [self._dev(p) for p, _ in subs if len(p) >= 3]
        if not polys:
            return
        x0, y0, x1, y1 = self._box(polys, 1)
        if x1 <= x0 or y1 <= y0:
            return
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        dr = ImageDraw.Draw(mask)
        for q in polys:
            dr.polygon((q - (x0, y0)).ravel().tolist(), fill=255)
        self._paint(mask, x0, y0, self.fill)

    def _stroke_subs(self, subs):
        u = self._unit()
        w = self.lw * u
        wi = max(1, round(w))
        colour = self.stroke
        if w < wi:                                  # hairlines: thinner by fading
            colour = colour[:3] + (colour[3] * w / wi,)
        lines = []
        for p, closed in subs:
            q = self._dev(p + [p[0]] if closed else p)
            if len(q) < 2:
                continue
            if self.dash:
                pattern, phase = self.dash
                lines += _dashes(q, [v * u for v in pattern], phase * u)
            else:
                lines.append(q)
        if not lines:
            return
        x0, y0, x1, y1 = self._box(lines, wi + 2)
        if x1 <= x0 or y1 <= y0:
            return
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        dr = ImageDraw.Draw(mask)
        r = wi / 2.0
        for q in lines:
            q = q - (x0, y0)
            dr.line(q.ravel().tolist(), fill=255, width=wi, joint="curve" if wi > 2 else None)
            if self.cap == 1 and wi > 2:
                for x, y in (q[0], q[-1]):
                    dr.ellipse((x - r, y - r, x + r, y + r), fill=255)
        self._paint(mask, x0, y0, colour)

    # drawing calls
    def beginPath(self):
        return Path()

    def clipPath(self, path, stroke=0, fill=0, fillMode=None):
        q = np.vstack([self._dev(p) for p, _ in path.subs])
        x0, y0 = np.floor(q.min(0)).astype(int)
        x1, y1 = np.ceil(q.max(0)).astype(int)
        cx0, cy0, cx1, cy1 = self.clip
        self.clip = (max(x0, cx0), max(y0, cy0), min(x1, cx1), min(y1, cy1))

    def drawPath(self, path, stroke=1, fill=0, fillMode=None):
        if fill:
            self._fill_subs(path.subs)
        if stroke:
            self._stroke_subs(path.subs)

    def line(self, x0, y0, x1, y1):
        self._stroke_subs([[[(x0, y0), (x1, y1)], False]])

    def rect(self, x, y, w, h, stroke=1, fill=0):
        p = Path()
        p.rect(x, y, w, h)
        self.drawPath(p, stroke, fill)

    def circle(self, x, y, r, stroke=1, fill=0):
        n = max(16, min(96, int(r * self._unit())))
        a = np.linspace(0, 2 * math.pi, n, endpoint=False)
        self.drawPath(_poly(list(zip(x + r * np.cos(a), y + r * np.sin(a))), True), stroke, fill)

    def bezier(self, x1, y1, x2, y2, x3, y3, x4, y4):
        p = Path()
        p.moveTo(x1, y1)
        p.curveTo(x2, y2, x3, y3, x4, y4)
        self._stroke_subs(p.subs)

    def drawImage(self, image, x, y, width, height, mask=None, preserveAspectRatio=False, anchor="c"):
        if isinstance(image, str):
            if image not in self.images:
                self.images[image] = Image.open(image).convert("RGB")
            image = self.images[image]
        q = self._dev([(x, y), (x + width, y + height)])
        x0, y0 = np.round(q.min(0)).astype(int)
        x1, y1 = np.round(q.max(0)).astype(int)
        im = image.resize((x1 - x0, y1 - y0), Image.LANCZOS)
        cx0, cy0, cx1, cy1 = self.clip
        a0, b0, a1, b1 = max(x0, cx0), max(y0, cy0), min(x1, cx1), min(y1, cy1)
        if a1 > a0 and b1 > b0:
            self.img.paste(im.crop((a0 - x0, b0 - y0, a1 - x0, b1 - y0)), (a0, b0))

    def _font(self, name, px):
        key = (name, round(px * 8) / 8)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(os.path.join(FONT_DIR, tm.FONTS[name]), max(key[1], 1.0))
        return self.fonts[key]

    def _text(self, x, y, s, font, size, mode):
        if not s.strip():
            return
        (a, c, _), (b, d, _) = self.m
        sx, sy = math.hypot(a, b), math.hypot(c, d)
        ang = math.degrees(math.atan2(-b, a))
        f = self._font(font, size * sy)
        sw = self.lw * sy / 2 if mode == 1 else 0
        colour = self.stroke if mode == 1 else self.fill
        l, t, r, btm = f.getbbox(s, anchor="ls", stroke_width=sw)
        pad = 2 + math.ceil(sw)
        mask = Image.new("L", (math.ceil(r - l) + 2 * pad, math.ceil(btm - t) + 2 * pad), 0)
        ox, oy = pad - l, pad - t                       # the text origin in the mask
        ImageDraw.Draw(mask).text((ox, oy), s, font=f, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
        if abs(sx / sy - 1) > 0.005:
            k = sx / sy
            mask = mask.resize((max(1, round(mask.width * k)), mask.height), Image.BICUBIC)
            ox *= k
        if abs(ang) > 0.05:
            rr = math.ceil(max(math.hypot(px - ox, py - oy) for px in (0, mask.width) for py in (0, mask.height))) + 2
            sq = Image.new("L", (2 * rr, 2 * rr), 0)
            sq.paste(mask, (round(rr - ox), round(rr - oy)))
            mask, ox, oy = sq.rotate(ang, resample=Image.BICUBIC, center=(rr, rr)), rr, rr
        dx, dy = self._dev([(x, y)])[0]
        self._paint(mask, round(dx - ox), round(dy - oy), colour)

    def drawString(self, x, y, s):
        self._text(x, y, s, self.font, self.size, 0)

    def drawCentredString(self, x, y, s):
        self._text(x - pdfmetrics.stringWidth(s, self.font, self.size) / 2, y, s, self.font, self.size, 0)

    def drawRightString(self, x, y, s):
        self._text(x - pdfmetrics.stringWidth(s, self.font, self.size), y, s, self.font, self.size, 0)

    def beginText(self, x=0, y=0):
        return TextObject(x, y)

    def drawText(self, t):
        self._text(t.x, t.y, t.s, t.font or self.font, t.size or self.size, t.mode)

    def result(self, ss):
        return self.img.reduce(ss) if ss > 1 else self.img


def _poly(pts, close=False):
    p = Path()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if close:
        p.close()
    return p


def page_canvas(size_px, ss, bg, x0_pt, top_pt, sx, sy, ox=0.0, oy=0.0):
    """A Raster where page point (x0_pt, top_pt) lands at final pixel (ox, oy), sx / sy pixels per point."""
    m = [sx * ss, 0, (ox - x0_pt * sx) * ss, 0, -sy * ss, (oy + top_pt * sy) * ss]
    return Raster((size_px[0] * ss, size_px[1] * ss), bg, m)


def grain(img, amount, seed):
    """Paper grain: faint blotches and fine noise over a finished image."""
    rng = np.random.default_rng(seed)
    w, h = img.size
    g = rng.standard_normal((h // 6 + 1, w // 6 + 1), dtype=np.float32)
    g = np.asarray(Image.fromarray(g).resize((w, h), Image.BICUBIC)) * 0.6
    g += rng.standard_normal((h, w), dtype=np.float32) * 0.45
    a = np.asarray(img, np.float32) + (g * amount)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


@contextmanager
def texture_layout(width_pt):
    """topo_map draws the map MAP_W points wide; a smaller map makes type and lines larger
    relative to it. Its scale bar is laid out for the PDF's 2 km, so the texture's own goes in."""
    old = tm.MAP_W, tm.scale_bar
    tm.MAP_W, tm.scale_bar = width_pt, sheet_scale_bar
    try:
        yield
    finally:
        tm.MAP_W, tm.scale_bar = old


def sheet_scale_bar(c, x, y):
    """topo_map.scale_bar with a 3 km bar and a box fitted to it, in the map's lower right corner."""
    km = tm.MAP_W / tm.SIZE * 1000
    marks = [0, 0.5, 1, 2, 3]
    note = "1:36 000   Grid 1 km   Contours 20 m, bold every 100 m"
    inner = max(pdfmetrics.stringWidth(note, "N", 7), marks[-1] * km + 4 + pdfmetrics.stringWidth("km", "N", 7))
    x1 = tm.MX0 + tm.MAP_W - 5 * MM
    x = x1 - inner - 14 * MM
    y = tm.MY0 + 9 * MM
    c.setFillColor(rgb((255, 255, 255), 0.88))
    c.setStrokeColor(rgb((0, 0, 0)))
    c.setLineWidth(0.4)
    c.rect(x - 4 * MM, y - 5 * MM, x1 - x + 4 * MM, 16 * MM, stroke=1, fill=1)
    for i in range(len(marks) - 1):
        c.setFillColor(rgb((0, 0, 0) if i % 2 == 0 else (255, 255, 255)))
        c.rect(x + marks[i] * km, y, (marks[i + 1] - marks[i]) * km, 1.6 * MM, stroke=1, fill=1)
    c.setFillColor(rgb((0, 0, 0)))
    c.setFont("N", 7)
    for v in marks:
        c.drawCentredString(x + v * km, y + 2.6 * MM, ("%g" % v).replace(".", ","))
    c.drawString(x + marks[-1] * km + 4, y + 0.2 * MM, "km")
    c.drawString(x, y - 3.4 * MM, note)
    nx = x + inner + 7 * MM
    c.drawPath(_poly([(nx, y + 7 * MM), (nx - 2.2 * MM, y), (nx, y + 1.5 * MM), (nx + 2.2 * MM, y)], True),
               stroke=0, fill=1)
    c.setFont("AB", 9)
    c.drawCentredString(nx, y - 3.4 * MM, "N")


def fit(strings, font, width):
    """The type size at which the strings, side by side, fill the width."""
    return width / sum(pdfmetrics.stringWidth(s, font, 1.0) for s in strings)


# ------------------------------------------------------------------ shared panels

def legend_block(c, x0, top, w, rows, row_h, size, names=True):
    """The legend box of the PDF's sidebar, at any width: header, NAMES samples, rows of symbols."""
    head = size * 2.1
    sample = [("GATLINBURG", "NB", 11), ("Town", "NB", 9), ("Village", "NB", 7.5), ("Peak", "NBI", 7),
              ("Gap", "NI", 6.5), ("Creek", "NI", 6.5)]
    k = size / 9.0
    names_h = 0.0
    if names:
        sx0 = x0 + w * 0.27
        line_w = sum(pdfmetrics.stringWidth(s, f, z * k) + 2.4 * MM * k for s, f, z in sample) - 2.4 * MM * k
        two = sx0 + line_w > x0 + w - size * 0.6
        names_h = size * (3.4 if two else 2.0)
    h = head + names_h + row_h * len(rows) + size * 0.5
    c.setFillColor(rgb((255, 255, 255)))
    c.setStrokeColor(rgb((60, 60, 60)))
    c.setLineWidth(0.5)
    c.rect(x0, top - h, w, h, stroke=1, fill=1)
    c.setFillColor(rgb(GREEN_PANEL))
    c.rect(x0, top - head, w, head, stroke=0, fill=1)
    c.setFillColor(rgb((255, 255, 255)))
    c.setFont("NB", size * 1.65)
    c.drawRightString(x0 + w - size * 0.7, top - head + head * 0.24, "LEGEND")
    y = top - head
    if names:
        by = y - size * 1.45
        c.setFillColor(rgb((20, 20, 20)))
        c.setFont("N", size)
        c.drawString(x0 + size * 0.8, by, "NAMES")
        sx = x0 + w * 0.27
        for s, f, z in sample:
            z *= k
            sw = pdfmetrics.stringWidth(s, f, z)
            if sx + sw > x0 + w - size * 0.6:
                sx, by = x0 + w * 0.27, by - size * 1.35
            c.setFont(f, z)
            c.setFillColor(rgb((20, 90, 180) if s == "Creek" else ((60, 35, 20) if s in ("Peak", "Gap") else (10, 10, 10))))
            c.drawString(sx, by, s)
            sx += sw + 2.4 * MM * k
        y -= names_h
    ks = 1.45 * row_h / (7.0 * MM)
    for name, kind in rows:
        y -= row_h
        c.setStrokeColor(rgb((215, 215, 215)))
        c.setLineWidth(0.3)
        c.line(x0 + size * 0.5, y - row_h * 0.31, x0 + w - size * 0.5, y - row_h * 0.31)
        c.setFillColor(rgb((20, 20, 20)))
        c.setFont("N", size)
        c.drawString(x0 + size * 0.8, y, name)
        c.saveState()
        c.translate(x0 + w * 0.63, y + row_h * 0.157)
        c.scale(ks, ks)
        legend_symbol(c, kind, 0, 0, w * 0.34 / ks)
        c.restoreState()
    return top - h


def crop_to(im, aspect, cx=0.53, cy=0.62, sky=0.16):
    """The largest crop of an image with this width / height, centred near (cx, cy), below
    the top `sky` of the image."""
    im = im.crop((0, round(im.height * sky), im.width, im.height))
    w, h = im.size
    if w / h > aspect:
        nw = round(h * aspect)
        x = min(max(round(cx * w - nw / 2), 0), w - nw)
        return im.crop((x, 0, x + nw, h))
    nh = round(w / aspect)
    y = min(max(round(cy * h - nh / 2), 0), h - nh)
    return im.crop((0, y, w, y + nh))


def inset_fitted(c, d, x, y, w, h):
    """topo_map.inset, leaving out the towns whose names would run off its edge (the
    same projection: the park's bounds plus 6 km, fitted and centred)."""
    rings = [[utm(la, lo, 17) for la, lo in way] for way in d["park"]]
    allp = np.array([p for r in rings for p in r])
    e0, n0 = allp.min(0) - 6000
    e1, n1 = allp.max(0) + 6000
    s = min(w / (e1 - e0), h / (n1 - n0))
    ox, oy = (w - (e1 - e0) * s) / 2, (h - (n1 - n0) * s) / 2
    taken = []                                  # the inset's fixed names
    for name, f, z, fx, fy in (("TENNESSEE", "NB", 9, 0.30, 0.80), ("NORTH CAROLINA", "NB", 9, 0.70, 0.16),
                               ("Great Smoky Mountains National Park", "NBI", 7.5, 0.66, 0.40)):
        tw = pdfmetrics.stringWidth(name, f, z)
        taken.append((w * fx - tw / 2, h * fy - 1, w * fx + tw / 2, h * fy + z * 0.75))
    towns = []
    for name, la, lo in d["towns_inset"]:
        e, n = utm(la, lo, 17)
        tx, ty = ox + (e - e0) * s, oy + (n - n0) * s
        b = (tx - 1.5, ty - 2.5, tx + 2.5 + pdfmetrics.stringWidth(name, "N", 6.5), ty + 3.5)
        if not (3 < tx and b[2] < w - 2 and 6 < ty < h - 6):
            continue
        if any(b[0] < t[2] and b[2] > t[0] and b[1] < t[3] and b[3] > t[1] for t in taken):
            continue
        taken.append(b)
        towns.append((name, la, lo))
    inset(c, dict(d, towns_inset=towns), x, y, w, h)


def title_panel(c, cover, x0, y0, w, h, credits=True, bleed=(0.0, 0.0)):
    """The PDF's title panel at any size: edition, the rendered view with the title
    over its foot, the two banners and TOPOGRAPHIC MAP 1:36 000. The view runs
    `bleed` points out past the left and right edges."""
    c.setFillColor(rgb(GREEN_PANEL))
    c.rect(x0 - bleed[0], y0, w + bleed[0] + bleed[1], h, stroke=0, fill=1)
    m = w * 0.045
    # Bottom line.
    fb = min(fit(["TOPOGRAPHIC MAP", "1:36 000"], "NB", w - 2 * m - w * 0.1), w * 0.075)
    c.setFillColor(rgb((255, 255, 255)))
    c.setFont("NB", fb)
    c.drawString(x0 + m, y0 + m * 0.9, "TOPOGRAPHIC MAP")
    c.drawRightString(x0 + w - m, y0 + m * 0.9, "1:36 000")
    # Banners.
    b1, b2 = "GATLINBURG & MT. LE CONTE", "HIKING TRAILS"
    gap = m * 0.6
    fz = min(fit([b1, b2], "NB", w - 2 * m - gap - 4 * 0.5 * fb), fb * 0.8)
    pad = 0.5 * fb
    bh = fz * 1.75
    by = y0 + m * 0.9 + fb * 1.05 + m * 0.5
    w1 = pdfmetrics.stringWidth(b1, "NB", fz) + 2 * pad
    c.setFillColor(rgb((255, 255, 255)))
    c.rect(x0 + m, by, w1, bh, stroke=0, fill=1)
    c.setFillColor(rgb(RED))
    c.rect(x0 + m + w1 + gap, by, w - 2 * m - w1 - gap, bh, stroke=0, fill=1)
    c.setFont("NB", fz)
    c.setFillColor(rgb(GREEN_PANEL))
    c.drawCentredString(x0 + m + w1 / 2, by + bh * 0.3, b1)
    c.setFillColor(rgb((255, 255, 255)))
    c.drawCentredString(x0 + m + w1 + gap + (w - 2 * m - w1 - gap) / 2, by + bh * 0.3, b2)
    # Edition boxes and credits at the top.
    top = y0 + h
    fe = fb * 0.62
    eh = fe * 1.7
    ey = top - m - eh
    e1, e2 = "1ST EDITION", "2026"
    we1 = pdfmetrics.stringWidth(e1, "NB", fe) + fe * 1.2
    we2 = pdfmetrics.stringWidth(e2, "NB", fe) + fe * 1.2
    c.setFillColor(rgb((255, 255, 255)))
    c.rect(x0 + w - m - we2 - we1, ey, we1, eh, stroke=0, fill=1)
    c.setFillColor(rgb(RED))
    c.rect(x0 + w - m - we2, ey, we2, eh, stroke=0, fill=1)
    c.setFont("NB", fe)
    c.setFillColor(rgb(GREEN_PANEL))
    c.drawCentredString(x0 + w - m - we2 - we1 / 2, ey + eh * 0.3, e1)
    c.setFillColor(rgb((255, 255, 255)))
    c.drawCentredString(x0 + w - m - we2 / 2, ey + eh * 0.3, e2)
    img_top = ey - m * 0.8
    if credits:
        fc = fe * 0.62
        c.setFont("N", fc)
        lines = ["A DayZ terrain by PackJC, drawn from its own heights and objects.",
                 "Roads, trails, water, places \u00a9 OpenStreetMap contributors, ODbL.",
                 "A game map: not for real-world navigation."]
        for i, s in enumerate(lines):
            c.drawString(x0 + m, img_top - fc * (1.0 + 1.25 * i), s)
        img_top -= fc * (1.0 + 1.25 * len(lines)) + m * 0.4
    # The view, with the title over its foot.
    img_y = by + bh + m * 0.7
    ih = img_top - img_y
    iw = w + bleed[0] + bleed[1]
    c.drawImage(crop_to(cover, iw / ih), x0 - bleed[0], img_y, iw, ih)
    size = min(0.92 * w / pdfmetrics.stringWidth(s, "T", 1) for s in ("GREAT SMOKY", "MOUNTAINS"))
    c.setFillColor(rgb((0, 0, 0), 0.30))
    c.rect(x0 - bleed[0], img_y, iw, size * 1.85, stroke=0, fill=1)
    text(c, x0 + w / 2, img_y + size * 0.95, "GREAT SMOKY", "T", size, (255, 255, 255), anchor="c",
         halo=(20, 40, 30), halo_w=size * 0.06, halo_a=0.6)
    text(c, x0 + w / 2, img_y + size * 0.12, "MOUNTAINS", "T", size, (255, 255, 255), anchor="c",
         halo=(20, 40, 30), halo_w=size * 0.06, halo_a=0.6)


# ------------------------------------------------------------------ the three textures

def unfolded(d, relief_jpg):
    map_pt = FRAME_H / PX_PER_PT                    # the map's width in points for topo_map
    sy = PX_PER_PT
    sx = FRAME_W / map_pt
    top_pt = tm.MY0 + map_pt
    c = page_canvas((TEX, TEX), SS, PAPER, tm.MX0, top_pt, sx, sy, FRAME_X0, FRAME_Y0)
    with texture_layout(map_pt):
        tm.draw_map(c, d, relief_jpg)
    # Title band over the grid numbers.
    bw = map_pt
    bt = top_pt + (FRAME_Y0 - BAND_Y0) / sy
    bb = top_pt + (FRAME_Y0 - BAND_Y1) / sy
    bh = bt - bb
    x0 = tm.MX0
    c.setFillColor(rgb(GREEN_PANEL))
    c.rect(x0, bb, bw, bh, stroke=0, fill=1)
    m = bh * 0.2
    size = bh * 0.78
    text(c, x0 + m, bb + bh * 0.19, "GREAT SMOKY MOUNTAINS", "T", size, (255, 255, 255),
         halo=(20, 40, 30), halo_w=1.4, halo_a=0.5)
    sx_ = x0 + m * 2 + pdfmetrics.stringWidth("GREAT SMOKY MOUNTAINS", "T", size)
    fz = bh * 0.34
    pad = fz * 0.5
    b1, b2 = "GATLINBURG & MT. LE CONTE", "HIKING TRAILS"
    w1 = pdfmetrics.stringWidth(b1, "NB", fz) + 2 * pad
    w2 = pdfmetrics.stringWidth(b2, "NB", fz) + 2 * pad
    by, bh2 = bb + bh * 0.24, fz * 1.75
    c.setFillColor(rgb((255, 255, 255)))
    c.rect(sx_, by, w1, bh2, stroke=0, fill=1)
    c.setFillColor(rgb(RED))
    c.rect(sx_ + w1 + m * 0.5, by, w2, bh2, stroke=0, fill=1)
    c.setFont("NB", fz)
    c.setFillColor(rgb(GREEN_PANEL))
    c.drawCentredString(sx_ + w1 / 2, by + bh2 * 0.3, b1)
    c.setFillColor(rgb((255, 255, 255)))
    c.drawCentredString(sx_ + w1 + m * 0.5 + w2 / 2, by + bh2 * 0.3, b2)
    c.setFont("NB", bh * 0.36)
    c.drawRightString(x0 + bw - m, bb + bh * 0.52, "TOPOGRAPHIC MAP   1:36 000")
    c.setFont("N", bh * 0.17)
    c.drawRightString(x0 + bw - m, bb + bh * 0.2,
                      "1st edition 2026  \u00b7  A DayZ terrain by PackJC  \u00b7  "
                      "Roads, trails, water, places and buildings \u00a9 OpenStreetMap contributors, ODbL")
    return grain(c.result(SS), 2.2, 1)


def legend_strip(d, cover):
    s = STRIP_PX
    h_pt = STRIP_H / s
    ss = 4
    c = page_canvas((STRIP_W, STRIP_H), ss, GREEN_PANEL, 0, h_pt, s, s)
    used = STRIP_USED / s
    mg = 7 / s
    x0, w = mg, used - 2 * mg
    bottom = legend_block(c, x0, h_pt - mg, w, LEGEND_ROWS, 16.2, 8.6)
    ih = 222.0
    inset_fitted(c, d, x0, bottom - mg * 1.4 - ih, w, ih)
    ptop = bottom - mg * 2.8 - ih
    title_panel(c, cover, 0, 0, used, ptop)
    return grain(c.result(ss), 2.5, 2)


def edge_strip(img, box, src, rng):
    """Layers of folded map seen edge on: white paper edges flecked with map colours, thin dark
    gaps, and the shadow under the stack."""
    x0, y0, x1, y1 = box
    k = 4
    w, h = (x1 - x0) * k, (y1 - y0) * k
    out = np.empty((h, w, 3), np.float32)
    out[:] = (14, 16, 14)
    yy = np.arange(h, dtype=np.float32)[:, None]
    xs = np.arange(w, dtype=np.float32)[None, :]
    sw, sh = src.size
    n = max(4, round((y1 - y0) / 3.2))
    gap = h / n
    for i in range(n):
        yc = (i + 0.5) * gap
        wave = (np.sin(xs / w * rng.uniform(3, 9) + rng.uniform(0, 6.3)) * rng.uniform(0.2, 0.55) * gap
                + np.sin(xs / w * rng.uniform(20, 40) + rng.uniform(0, 6.3)) * 0.08 * gap)
        th = gap * rng.uniform(0.3, 0.44)
        row = rng.integers(0, sh)
        a = rng.uniform(0, 0.6)
        line = np.asarray(src.crop((round(a * sw), row, round(a * sw + sw * 0.4), row + 1)).resize((w, 1), Image.BILINEAR),
                          np.float32)[0]
        tint = rng.uniform(0.2, 0.6)
        col = np.array((250, 250, 246), np.float32) * (1 - tint) + line * tint
        col *= rng.uniform(0.82, 1.0)
        m = np.clip(th - np.abs(yy - yc - wave), 0, 1.0)
        out = out * (1 - m[..., None]) + col[None, :, :] * m[..., None]
    t = np.clip((yy / h - 0.62) / 0.38, 0, 1)
    out *= (1 - 0.7 * t * t * (3 - 2 * t))[..., None]
    im = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).reduce(k)
    img.paste(im, (x0, y0))


def folded(d, cover, sheet):
    size = 512
    ss = 4
    img = Image.new("RGB", (size, size), GREEN_DARK)

    def panel(island, safe, s, bg):
        """A canvas over the island's bounds (+3 px) at s px per point; the safe rectangle in its points."""
        ax0, ay0 = math.floor(island[0]) - 3, math.floor(island[1]) - 3
        ax1, ay1 = math.ceil(island[2]) + 3, math.ceil(island[3]) + 3
        ay0 = max(ay0, 0)
        h_pt = (ay1 - ay0) / s
        c = page_canvas((ax1 - ax0, ay1 - ay0), ss, bg, 0, h_pt, s, s)
        x0, x1 = (safe[0] - ax0) / s, (safe[2] - ax0) / s
        y0, y1 = h_pt - (safe[3] - ay0) / s, h_pt - (safe[1] - ay0) / s
        return c, (ax0, ay0), (x0, y0, x1 - x0, y1 - y0), (x0, (ax1 - ax0) / s - x1)

    # Front cover: the title panel, the view bleeding out to the worn edges.
    c, at, (x0, y0, w, h), bleed = panel(FRONT, FRONT_SAFE, 1.0, GREEN_PANEL)
    title_panel(c, cover, x0, y0, w, h, credits=False, bleed=bleed)
    img.paste(c.result(ss), at)
    # Back panel: legend excerpt over the locator inset, upright.
    c, at, (x0, y0, w, h), _ = panel(BACK, BACK_SAFE, 1.0, (238, 238, 232))
    rows = [r for r in LEGEND_ROWS if r[1] in BACK_ROWS]
    bottom = legend_block(c, x0, y0 + h, w, rows, 12.4, 7.0, names=False)
    inset_fitted(c, d, x0, y0, w, bottom - y0 - 5)
    img.paste(c.result(ss), at)
    # Edge strips: layers of map.
    rng = np.random.default_rng(5)
    small = sheet.crop((FRAME_X0, FRAME_Y0, FRAME_X1, FRAME_Y1)).resize((1024, 1024), Image.BOX)
    for x0, y0, x1, y1 in STRIPS:
        edge_strip(img, (math.floor(x0) - 3, math.floor(y0) - 2, math.ceil(x1) + 3, math.ceil(y1) + 2), small, rng)
    return grain(img, 2.5, 3)


# ------------------------------------------------------------------ main

def main():
    png_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "source", "maptex")
    paa_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data")
    i2p = sys.argv[3] if len(sys.argv) > 3 else I2P
    os.makedirs(png_dir, exist_ok=True)
    tm.register_fonts()
    d = tm.load()
    d["elev_smooth"] = box_blur(d["elev"], 1, 2)        # as topo_map.relief() leaves it, for contour heights
    cover = Image.open(os.path.join(ROOT, "map", "cover.jpg")).convert("RGB")
    sheet = unfolded(d, os.path.join(ROOT, "map", "relief.jpg"))
    print("unfolded map drawn", flush=True)
    files = {"map_unfolded_co": sheet, "map_legend_co": legend_strip(d, cover), "map_folded_co": folded(d, cover, sheet)}
    for name, im in files.items():
        im.save(os.path.join(png_dir, name + ".png"))
        print("wrote", os.path.join(png_dir, name + ".png"), im.size)
    if os.path.isfile(i2p):
        os.makedirs(paa_dir, exist_ok=True)
        for name in files:
            dst = os.path.join(paa_dir, name + ".paa")
            if os.path.exists(dst):
                os.remove(dst)
            subprocess.run([i2p, os.path.join(png_dir, name + ".png"), dst], capture_output=True, timeout=300)
            if not os.path.isfile(dst):
                sys.exit("ImageToPAA failed on " + name)
            print("wrote", dst, "(%.1f MB)" % (os.path.getsize(dst) / 1e6))
    else:
        print("no ImageToPAA at %s: PNGs only" % i2p)


if __name__ == "__main__":
    main()
