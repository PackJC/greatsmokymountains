"""Draw a poster of the map's loot tiers, for posting: the tier of every spot over
hillshaded relief, with towns, peaks, roads, rivers, every building with loot, the
heli crash, supply drop, convoy and police scene spots, a 1 km grid and a legend
with what each tier holds.

    python tools/loot_map.py <mission folder> <out.jpg>

Tiers, buildings and event spots are read from the mission (areaflags.map,
mapgroupproto.xml, mapgrouppos.xml, cfgeventspawns.xml, db/types.xml and
db/events.xml, cfgeventgroups.xml), so the poster shows what the server uses; what
can spawn where is tools/check_loot.py's reckoning. Heights, roads and rivers
come from source/, place names from config.cpp, and guns' in-game names from the
game's configs on P: (DZ\\weapons, languagecore\\stringtable.csv).
"""

import csv
import glob
import json
import math
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import bilinear  # noqa: E402
from check_loot import reach  # noqa: E402
from mission import TIER_HEIGHTS  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "source")
SIZE = 20480.0
N = 4096                                     # map pixels per side (5 m)
SS = 2                                       # lines and symbols are drawn this much larger, then reduced
HEAD, CARD_H, FOOT = 470, 660, 1130
BG, PANEL, INK, GREY = (17, 19, 21), (30, 33, 36), (245, 245, 240), (165, 168, 170)
TIERS = [(52, 168, 83), (238, 196, 36), (243, 128, 32), (214, 44, 44)]
WATER = (64, 150, 232)
HELI, CRATE, CONVOY, POLICE = (220, 30, 30), (255, 150, 0), (96, 112, 44), (36, 72, 200)
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
GAME = "P:\\"
GUN_FOLDERS = ("firearms", "pistols", "shotguns", "archery")
MAJOR = ("motorway", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link")
MINOR = ("tertiary", "tertiary_link", "unclassified")
LOCAL = ("residential", "service", "living_street")
BLURBS = ["The starter tier: Gatlinburg, the valleys and the creek bottoms.", "Foothills and the lower slopes.",
          "Mountainsides and the upper valleys.", "The highest ridges and summits."]


def font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


def feet(m):
    return "{:,} ft".format(int(round(m / 0.3048, -1)))


# ------------------------------------------------------------------ data

def read_tiers(path):
    """areaflags.map value layer -> tier index 0-3 per 5 m cell, row 0 south."""
    with open(path, "rb") as fh:
        nx, nz = struct.unpack("<6i", fh.read(24))[:2]
        fh.seek(24 + nx * nz * 4)
        value = np.frombuffer(fh.read(nx * nz), np.uint8).reshape(nz, nx)
    lut = np.zeros(256, np.uint8)
    lut[[1, 2, 4, 8]] = [0, 1, 2, 3]
    return lut[value]


def events(mission):
    """Active events with spots: name -> (spots, how many at a time, child types)."""
    defs = {}
    for e in ET.parse(os.path.join(mission, "db", "events.xml")).getroot().iter("event"):
        if e.findtext("active", "0") == "1":
            defs[e.get("name")] = (int(e.findtext("nominal", "0")), [c.get("type") for c in e.iter("child")])
    out = {}
    for e in ET.parse(os.path.join(mission, "cfgeventspawns.xml")).getroot().iter("event"):
        if e.get("name") in defs and defs[e.get("name")][0]:
            out[e.get("name")] = ([(float(p.get("x")), float(p.get("z"))) for p in e.iter("pos")],) + defs[e.get("name")]
    return out


def gun_names():
    """Gun class -> in-game name, from the game's weapon configs and stringtable (empty without them)."""
    strings = {}
    path = os.path.join(GAME, "languagecore", "stringtable.csv")
    if os.path.isfile(path):
        for row in csv.reader(open(path, encoding="utf-8", errors="replace")):
            if len(row) > 2:
                strings[row[0].lower()] = row[2]
    classes = {}
    for sub in GUN_FOLDERS:
        for f in glob.glob(os.path.join(GAME, "DZ", "weapons", sub, "**", "config.cpp"), recursive=True):
            parts = re.split(r"\bclass\s+(\w+)\s*(?::\s*(\w+))?\s*\{", open(f, errors="replace").read())
            for k in range(1, len(parts) - 2, 3):
                m = re.search(r'displayName\s*=\s*"([^"]*)"', parts[k + 2])
                classes[parts[k]] = (parts[k + 1], m.group(1) if m else None)

    def name(c, depth=0):
        parent, disp = classes.get(c, (None, None))
        if disp is None:
            return name(parent, depth + 1) if parent and depth < 12 else None
        return strings.get(disp[1:].lower()) if disp.startswith("$") else disp
    return {c: name(c) for c in classes if name(c)}


def place_names():
    text = open(os.path.join(ROOT, "config.cpp"), encoding="utf-8", errors="replace").read()
    return [(n, float(x), float(z), t) for n, x, z, t in
            re.findall(r'name="([^"]*)";\s*position\[\]=\{([\d.]+),([\d.]+)\};\s*type="(\w+)"', text)]


def tier_guns(items, guns):
    """Per tier: guns first found in buildings there, and guns found only at event wrecks and crates,
    lowest tier there; each in-game name once, at its lowest tier, the commonest first."""
    new, wrecks, seen = [[] for _ in range(4)], [[] for _ in range(4)], set()
    rows = [(min(i["building"] or i["event"]), not i["building"], -i["nominal"], c) for c, i in items.items()
            if c in guns and (i["building"] or i["event"])]
    for k, wreck_only, _, c in sorted(rows):
        if guns[c] not in seen:
            seen.add(guns[c])
            (wrecks if wreck_only else new)[k].append(guns[c])
    return new, wrecks


# ------------------------------------------------------------------ drawing

def relief(elev, tiers):
    """Tier colours shaded by the ground, with a dark line on each tier border. North up."""
    e = elev[::-1].astype(np.float32)
    gy, gx = np.gradient(e, 5.0)                 # per metre; rows run south
    alt, az = math.radians(40), math.radians(315)
    lx, ly, lz = math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt)
    nx, ny = -gx * 1.3, gy * 1.3                 # normal (east, north) with z = 1, a little exaggerated
    shade = (nx * lx + ny * ly + lz) / np.sqrt(nx * nx + ny * ny + 1) / lz
    k = np.clip(0.42 + 0.62 * shade, 0.28, 1.12)[..., None]
    col = np.asarray(TIERS, np.float32)[tiers[::-1]] * k
    col = col * 0.9 + 255 * 0.1 * k              # a touch of white so the colours read on dark slopes
    g = np.hypot(*np.gradient(e)) + 1e-3         # metres per pixel
    for t in TIER_HEIGHTS:
        a = (np.clip(2.0 - np.abs(e - t) / g, 0, 1) * 0.9)[..., None]
        col = col * (1 - a) + np.array((20, 20, 20), np.float32) * a
    return Image.fromarray(np.clip(col, 0, 255).astype(np.uint8))


def poly(d, pts, width, fill):
    d.line(pts, fill=fill, width=width, joint="curve")
    r = width / 2.0
    for u, v in (pts[0], pts[-1]):
        d.ellipse((u - r, v - r, u + r, v + r), fill=fill)


def heli_icon(d, u, v, s):
    d.ellipse((u - s, v - s, u + s, v + s), fill=HELI, outline=(255, 255, 255), width=max(2, s // 6))
    d.text((u, v + s * 0.04), "H", font=font("arialbd.ttf", int(s * 1.3)), fill=(255, 255, 255), anchor="mm")


def crate_icon(d, u, v, s):
    d.rectangle((u - s, v - s, u + s, v + s), fill=CRATE, outline=(30, 20, 0), width=max(2, s // 6))
    w = max(2, s // 5)
    d.line((u - s, v - s, u + s, v + s), fill=(30, 20, 0), width=w)
    d.line((u - s, v + s, u + s, v - s), fill=(30, 20, 0), width=w)


def convoy_icon(d, u, v, s):
    d.rounded_rectangle((u - s, v - s, u + s, v + s), radius=s // 3, fill=CONVOY, outline=(255, 255, 255),
                        width=max(2, s // 7))
    w = max(2, s // 5)
    for dy in (-0.3, 0.25):                      # sergeant's chevrons
        d.line([(u - s * 0.55, v + s * (dy + 0.25)), (u, v + s * (dy - 0.2)), (u + s * 0.55, v + s * (dy + 0.25))],
               fill=(255, 255, 255), width=w, joint="curve")


def police_icon(d, u, v, s):
    d.rounded_rectangle((u - s, v - s, u + s, v + s), radius=s // 3, fill=POLICE, outline=(255, 255, 255),
                        width=max(2, s // 7))
    star = [(u + s * (0.7 if k % 2 == 0 else 0.3) * math.sin(math.pi * k / 5),
             v - s * (0.7 if k % 2 == 0 else 0.3) * math.cos(math.pi * k / 5)) for k in range(10)]
    d.polygon(star, fill=(255, 255, 255))      # a sheriff's star


def peak_icon(d, u, v, s):
    d.polygon([(u, v - s), (u + s * 0.95, v + s * 0.7), (u - s * 0.95, v + s * 0.7)], fill=(25, 25, 25),
              outline=(255, 255, 255))


class Labels:
    """Places text blocks without overlaps: tries each position in turn, keeps blocks on the map."""

    def __init__(self, d, lo, hi):
        self.d, self.lo, self.hi, self.taken = d, lo, hi, []

    def block(self, u, v, lines, where, gap):
        sizes = [self.d.textbbox((0, 0), t, font=f, anchor="la", stroke_width=sw) for t, f, sw in lines]
        w = max(b[2] - b[0] for b in sizes)
        h = sum(b[3] - b[1] for b in sizes) + 2 * (len(lines) - 1)
        g = gap * 0.7
        x, y = {"center": (u - w / 2, v - h / 2), "above": (u - w / 2, v - gap - h), "below": (u - w / 2, v + gap),
                "right": (u + gap, v - h / 2), "left": (u - gap - w, v - h / 2), "ur": (u + g, v - g - h),
                "ul": (u - g - w, v - g - h), "lr": (u + g, v + g), "ll": (u - g - w, v + g)}[where]
        x = min(max(x, self.lo[0]), self.hi[0] - w)
        y = min(max(y, self.lo[1]), self.hi[1] - h)
        return (x, y, x + w, y + h), sizes

    def free(self, r, pad=6):
        return all(r[2] + pad < t[0] or t[2] + pad < r[0] or r[3] + pad < t[1] or t[3] + pad < r[1] for t in self.taken)

    def place(self, u, v, lines, wheres, gap=0, force=False):
        for where in wheres:
            r, sizes = self.block(u, v, lines, where, gap)
            if self.free(r) or (force and where == wheres[-1]):
                self.taken.append(r)
                y = r[1]
                for (t, f, sw), b in zip(lines, sizes):
                    lw = b[2] - b[0]
                    x = (r[2] - lw if where in ("left", "ul", "ll") else
                         r[0] if where in ("right", "ur", "lr") else (r[0] + r[2] - lw) / 2)
                    self.d.text((x - b[0], y - b[1]), t, font=f, fill=(255, 255, 255), anchor="la",
                                stroke_width=sw, stroke_fill=(15, 15, 15))
                    y += b[3] - b[1] + 2
                return True
        return False


def draw_map(elev, tiers, evs, buildings):
    base = relief(elev, tiers).resize((N * SS, N * SS), Image.BICUBIC)
    d = ImageDraw.Draw(base, "RGBA")
    px = N * SS / SIZE

    def xy(x, z):
        return x * px, (SIZE - z) * px

    for k in range(1, 20):                       # 1 km grid
        q = k * 1000 * px
        d.line((q, 0, q, N * SS), fill=(255, 255, 255, 46), width=SS)
        d.line((0, q, N * SS, q), fill=(255, 255, 255, 46), width=SS)
    widths = {"river": 4.5, "stream": 2.2, "brook": 1.4, "seasonal": 0}
    for ln in sorted(json.load(open(os.path.join(SRC, "water", "lines.json"))),
                     key=lambda ln: widths.get(ln.get("class"), 0)):
        w = widths.get(ln.get("class"), 0)
        if w and len(ln["points"]) > 1:
            poly(d, [xy(x, z) for x, z in ln["points"]], int(round(w * SS)), WATER + ((255,) if w > 2 else (190,)))
    roads = json.load(open(os.path.join(SRC, "roads", "lines.json")))
    for kinds, w, case, fill in [(LOCAL, 2.0, 0.0, (235, 235, 230)), (MINOR, 3.2, 1.6, (250, 250, 245)),
                                 (MAJOR, 5.0, 2.0, (255, 255, 255))]:
        lines = [[xy(x, z) for x, z in r["points"]] for r in roads if r.get("highway") in kinds and len(r["points"]) > 1]
        if case:
            for pts in lines:
                poly(d, pts, int(round((w + 2 * case) * SS)), (25, 25, 25, 210))
        for pts in lines:
            poly(d, pts, int(round(w * SS)), fill)
    s = 2.4 * SS
    for name, x, z in buildings:
        u, v = xy(x, z)
        d.rectangle((u - s, v - s, u + s, v + s), fill=(20, 20, 20), outline=(255, 255, 255, 150))
    for x, z in evs.get("StaticPoliceSituation", ([],))[0]:
        police_icon(d, *xy(x, z), 17 * SS)
    for x, z in evs.get("StaticMilitaryConvoy", ([],))[0]:
        convoy_icon(d, *xy(x, z), 19 * SS)
    for x, z in evs.get("StaticAirplaneCrate", ([],))[0]:
        crate_icon(d, *xy(x, z), 19 * SS)
    for x, z in evs.get("StaticHeliCrash", ([],))[0]:
        heli_icon(d, *xy(x, z), 25 * SS)
    img = base.resize((N, N), Image.LANCZOS)
    del base

    # Names at full size, so the text stays sharp: towns first, then peaks from the highest down.
    d = ImageDraw.Draw(img, "RGBA")
    px = N / SIZE
    labels = Labels(d, (54, 50), (N - 10, N - 10))
    ax, ay = N - 110, 210                        # north arrow
    sx, sy, km = 90, N - 110, 1000 * px          # scale bar
    labels.taken += [(ax - 60, ay - 160, ax + 60, ay + 50), (sx - 30, sy - 95, sx + 5 * km + 90, sy + 60)]
    for ev, s in (("StaticHeliCrash", 25), ("StaticAirplaneCrate", 19), ("StaticMilitaryConvoy", 19),
                  ("StaticPoliceSituation", 17)):          # names go round the event markers
        labels.taken += [(x * px - s, (SIZE - z) * px - s, x * px + s, (SIZE - z) * px + s)
                         for x, z in evs.get(ev, ([],))[0]]
    names = place_names()
    hills = sorted([n for n in names if n[3] == "Hill"], key=lambda n: -bilinear(elev, n[1] / 5.0, n[2] / 5.0))
    marks = {}
    for name, x, z, kind in hills:
        u, v = x * px, (SIZE - z) * px
        peak_icon(d, u, v, 11)
        marks[name] = (u - 12, v - 12, u + 12, v + 9)
        labels.taken.append(marks[name])
    towns = {"Capital": (font("impact.ttf", 104), 7), "City": (font("impact.ttf", 70), 5),
             "Village": (font("impact.ttf", 54), 4), "Local": (font("ARIALNBI.TTF", 38), 4)}
    around = ["above", "below", "right", "left", "ur", "ul", "lr", "ll"]

    def place_towns(kinds):
        for name, x, z, kind in names:
            if kind in kinds:
                f, sw = towns[kind]
                labels.place(x * px, (SIZE - z) * px, [(name.upper() if kind != "Local" else name, f, sw)],
                             ["center"] + around, gap=14, force=True)
    place_towns(("Capital", "City", "Village"))
    for k, (name, x, z, kind) in enumerate(hills):    # the highest peak a size up
        h = bilinear(elev, x / 5.0, z / 5.0)
        labels.taken.remove(marks[name])               # a peak's name may sit next to its own mark
        labels.place(x * px, (SIZE - z) * px, [(name, font("ARIALNB.TTF", 46 if k == 0 else 36), 5 if k == 0 else 4),
                                               ("{:,} m".format(int(round(h))), font("ARIALN.TTF", 36 if k == 0 else 30), 3)],
                     around, gap=20)
        labels.taken.append(marks[name])
    place_towns(("Local",))
    f = font("bahnschrift.ttf", 30)              # grid numbers: columns from the west, rows from the north
    for k in range(20):
        c = (k + 0.5) * 1000 * px
        d.text((c, 10), "%02d" % k, font=f, fill=(255, 255, 255), anchor="ma", stroke_width=3, stroke_fill=(0, 0, 0))
        d.text((12, c), "%02d" % k, font=f, fill=(255, 255, 255), anchor="lm", stroke_width=3, stroke_fill=(0, 0, 0))
    d.polygon([(ax, ay - 80), (ax + 40, ay + 40), (ax, ay + 15), (ax - 40, ay + 40)], fill=(255, 255, 255),
              outline=(0, 0, 0), width=4)
    d.text((ax, ay - 92), "N", font=font("impact.ttf", 64), fill=(255, 255, 255), anchor="md",
           stroke_width=5, stroke_fill=(0, 0, 0))
    d.rectangle((sx - 30, sy - 95, sx + 5 * km + 90, sy + 60), fill=(15, 15, 15, 190))
    for k in range(5):
        d.rectangle((sx + k * km, sy, sx + (k + 1) * km, sy + 22), fill=(255, 255, 255) if k % 2 == 0 else (60, 60, 60),
                    outline=(255, 255, 255), width=2)
    f = font("bahnschrift.ttf", 34)
    for k in range(6):
        d.text((sx + k * km, sy - 10), str(k), font=f, fill=(255, 255, 255), anchor="md")
    d.text((sx + 5 * km + 22, sy + 11), "km", font=f, fill=(255, 255, 255), anchor="lm")
    d.text((sx, sy + 30), "1 km grid squares", font=font("bahnschrift.ttf", 26), fill=GREY, anchor="la")
    return img


def wrap(d, text, f, width, max_lines):
    """Wrap a comma list to the width; the last line ends in ', ...' if it doesn't all fit."""
    words, lines = text.split(" "), [""]
    for w in words:
        trial = (lines[-1] + " " + w).strip()
        if d.textlength(trial, font=f) <= width:
            lines[-1] = trial
        elif len(lines) < max_lines:
            lines.append(w)
        else:
            lines[-1] = lines[-1].rstrip(",") + " ..."
            break
    return lines


def legend_item(d, x, y, kind, label, sub=None):
    u, v = x + 26, y + 26
    if kind == "heli":
        heli_icon(d, u, v, 26)
    elif kind == "crate":
        crate_icon(d, u, v, 20)
    elif kind == "convoy":
        convoy_icon(d, u, v, 22)
    elif kind == "police":
        police_icon(d, u, v, 21)
    elif kind == "building":
        d.rectangle((u - 9, v - 9, u + 9, v + 9), fill=(20, 20, 20), outline=(255, 255, 255))
    elif kind == "peak":
        peak_icon(d, u, v, 20)
    elif kind == "border":
        d.line((x, v, x + 52, v), fill=(20, 20, 20), width=8)
        d.line((x, v - 9, x + 52, v - 9), fill=TIERS[1], width=10)
        d.line((x, v + 9, x + 52, v + 9), fill=TIERS[2], width=10)
    elif kind == "road":
        d.line((x, v, x + 52, v), fill=(25, 25, 25), width=16)
        d.line((x, v, x + 52, v), fill=(255, 255, 255), width=10)
    elif kind == "water":
        d.line((x, v, x + 52, v), fill=WATER, width=10)
    d.text((x + 76, y + (8 if sub else 26)), label, font=font("bahnschrift.ttf", 40), fill=INK,
           anchor="la" if sub else "lm")
    if sub:
        d.text((x + 76, y + 56), sub, font=font("bahnschrift.ttf", 30), fill=GREY, anchor="la")


def poster(mission, out):
    elev = np.load(os.path.join(SRC, "buildings", "elevation.npy")).astype(np.float32)   # row 0 south
    tiers = read_tiers(os.path.join(mission, "areaflags.map"))
    if tiers.shape != (N, N) or elev.shape != (N, N):
        sys.exit("expected %d x %d tiers and heights" % (N, N))
    cell = SIZE / N

    def tier_at(x, z):
        return int(tiers[min(int(z / cell), N - 1), min(int(x / cell), N - 1)])
    evs = events(mission)
    buildings = [(g.get("name"), float(g.get("pos").split()[0]), float(g.get("pos").split()[2]))
                 for g in ET.parse(os.path.join(mission, "mapgrouppos.xml")).getroot().iter("group")]
    btier = [tier_at(x, z) for name, x, z in buildings]
    share = [100.0 * (tiers == k).mean() for k in range(4)]
    items = reach(mission)
    counts = [sum(1 for i in items.values() if k in i["building"] | i["event"]) for k in range(4)]
    guns = gun_names()
    new, crash = tier_guns(items, guns)
    print("tiers: %s %% of the map; buildings %s; item types that can spawn %s; %d gun names"
          % ([round(s) for s in share], [btier.count(k) for k in range(4)], counts, len(guns)), flush=True)
    for k in range(4):
        print("  tier %d new guns: %s | at wrecks only: %s" % (k + 1, ", ".join(new[k]), ", ".join(crash[k])))

    img = Image.new("RGB", (N, HEAD + N + FOOT), BG)
    img.paste(draw_map(elev, tiers, evs, buildings), (0, HEAD))
    d = ImageDraw.Draw(img)

    # Header: logo, title, the rule.
    logo = Image.open(os.path.join(SRC, "logo", "logo.png")).convert("RGBA").resize((HEAD - 70, HEAD - 70), Image.LANCZOS)
    img.paste(logo, (60, 35), logo)
    tx = 60 + HEAD - 70 + 50
    d.text((tx, 40), "GREAT SMOKY MOUNTAINS", font=font("impact.ttf", 170), fill=INK, anchor="la")
    d.text((tx, 232), "LOOT TIERS", font=font("impact.ttf", 120), fill=TIERS[3], anchor="la")
    tw = d.textlength("LOOT TIERS", font=font("impact.ttf", 120))
    d.text((tx + tw + 40, 300), "the higher you climb, the better the loot", font=font("bahnschrift.ttf", 62),
           fill=INK, anchor="ls")
    d.text((tx, 395), "Every spot's tier is set by its height above sea level. Tier 1 is the valleys and "
                      "Gatlinburg, tier 4 the high ridges round Mount Le Conte and the state line.",
           font=font("bahnschrift.ttf", 38), fill=GREY, anchor="la")
    d.text((N - 60, 40), "DayZ  |  20.48 x 20.48 km", font=font("bahnschrift.ttf", 40), fill=GREY, anchor="ra")

    # Footer: one card per tier, then the symbols.
    y0 = HEAD + N + 50
    gap, cx = 40, 60
    cw = (N - 2 * cx - 3 * gap) // 4
    hs = TIER_HEIGHTS
    bands = (["below %d m" % hs[0]] + ["%d - %d m" % (hs[k], hs[k + 1]) for k in range(len(hs) - 1)]
             + ["above %d m" % hs[-1]])
    bands_ft = (["below " + feet(hs[0])] + ["%s - %s" % (feet(hs[k]), feet(hs[k + 1])) for k in range(len(hs) - 1)]
                + ["above " + feet(hs[-1])])
    small, label_f = font("bahnschrift.ttf", 32), font("bahnschrift.ttf", 32)
    for k in range(4):
        x = cx + k * (cw + gap)
        d.rounded_rectangle((x, y0, x + cw, y0 + CARD_H), radius=26, fill=PANEL)
        d.rounded_rectangle((x, y0, x + cw, y0 + 120), radius=26, fill=TIERS[k])
        d.rectangle((x, y0 + 94, x + cw, y0 + 120), fill=TIERS[k])
        d.text((x + 34, y0 + 60), "TIER %d" % (k + 1), font=font("impact.ttf", 92), fill=(15, 15, 15), anchor="lm")
        d.text((x + cw - 34, y0 + 60), "%d%% of the map" % round(share[k]), font=font("impact.ttf", 56),
               fill=(15, 15, 15), anchor="rm")
        d.text((x + 34, y0 + 150), bands[k], font=font("bahnschrift.ttf", 56), fill=INK, anchor="la")
        d.text((x + 34, y0 + 218), bands_ft[k], font=font("bahnschrift.ttf", 38), fill=GREY, anchor="la")
        d.text((x + 34, y0 + 284), "{:,} buildings with loot".format(btier.count(k)),
               font=font("bahnschrift.ttf", 40), fill=INK, anchor="la")
        d.text((x + 34, y0 + 336), "{:,} item types can spawn".format(counts[k]),
               font=font("bahnschrift.ttf", 40), fill=INK, anchor="la")
        y = y0 + 404
        for title, colour, names in (("Guns:" if k == 0 else "New guns:", TIERS[k], new[k]),
                                     ("At wrecks:", (255, 110, 110), crash[k])):
            if not names:
                continue
            d.text((x + 34, y), title, font=label_f, fill=colour, anchor="la")
            indent = d.textlength(title + " ", font=label_f)
            lines = wrap(d, ", ".join(names), small, cw - 68 - indent, 2)
            for line in lines:
                d.text((x + 34 + indent, y), line, font=small, fill=INK, anchor="la")
                y += 42
            y += 10
        d.text((x + 34, y0 + CARD_H - 34), BLURBS[k], font=font("bahnschrift.ttf", 30), fill=GREY, anchor="ls")
    heli, heli_n = evs.get("StaticHeliCrash", ([], 0))[:2]
    crate, crate_n = evs.get("StaticAirplaneCrate", ([], 0))[:2]
    convoy, convoy_n = evs.get("StaticMilitaryConvoy", ([], 0))[:2]
    police, police_n = evs.get("StaticPoliceSituation", ([], 0))[:2]
    y1 = y0 + CARD_H + 50
    cols = [(cx, [("heli", "Heli crash site", "%d spots, %d crashed at a time" % (len(heli), heli_n)),
                  ("crate", "Supply drop", "%d spots, %d at a time" % (len(crate), crate_n)),
                  ("convoy", "Military convoy", "%d spots, %d at a time" % (len(convoy), convoy_n))]),
            (cx + 1010, [("police", "Roadblock, crash or abandoned cars", "%d spots, %d at a time" % (len(police), police_n)),
                         ("building", "Building with loot", "{:,} on the map".format(len(buildings))),
                         ("peak", "Peak", "height in metres")]),
            (cx + 2010, [("border", "Tier border", "at %s m" % " / ".join("%d" % t for t in hs)),
                         ("road", "Road", None), ("water", "River and creeks", None)])]
    for x, entries in cols:
        for k, (kind, label, sub) in enumerate(entries):
            legend_item(d, x, y1 + k * 105, kind, label, sub)
    for k, line in enumerate(("Military-only weapons and gear spawn only", "at heli crashes, supply drops and",
                              "military convoys. Wrecks come and go:", "only so many are out at a time.")):
        d.text((cx + 2900, y1 + 10 + 46 * k), line, font=font("bahnschrift.ttf", 34), fill=INK if k < 3 else GREY,
               anchor="la")
    img.save(out, quality=90, subsampling=0, optimize=True)
    print("wrote %s (%d x %d, %.1f MB)" % (out, img.size[0], img.size[1], os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    poster(sys.argv[1], sys.argv[2])
