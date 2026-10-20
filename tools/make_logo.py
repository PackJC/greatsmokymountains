"""Draw the mod's logo in the style of PackJC's other mods: a 1024 px square
on transparent, an emblem inside a 16 px frame; logo.png in greys with a black
frame, logo_hover.png in colour with an orange frame.

    python tools/make_logo.py source/buildings/elevation.npy <png folder> [<paa folder> <ImageToPAA.exe>]

The emblem is the real skyline seen from Gatlinburg towards Mt. Le Conte,
traced from the map's own heights in six bands of distance (the layered,
hazy ridges the Smokies are named for), with spruces on the nearest ridge and
GREAT SMOKY MOUNTAINS across it. With a paa folder it also writes logo.paa and
logo_hover.paa there (data/ in the addon, for mod.cpp).
"""

import math
import os
import random
import subprocess
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

SIZE = 20480.0
N = 2048                                    # drawn at twice the size, then reduced
VIEW = (3645.0, 14643.0)                    # Gatlinburg
TARGET = (10115.0, 7820.0)                  # Mt. Le Conte
FOV = 84.0
BANDS = [1300.0, 2600.0, 4300.0, 6800.0, 10500.0, 24000.0]
EXAGGERATE = 1.7
CX, CY, RX, RY = 1024, 890, 820, 540        # the oval
FRAME = 32
SKY_TOP, SKY_LOW = (118, 158, 214), (255, 206, 140)
RIDGE_FAR, RIDGE_NEAR = (122, 146, 190), (26, 44, 66)
MIST = (226, 232, 242)
TREE = (14, 30, 30)
TEXT_HOVER, HOVER_FRAME = (78, 196, 70), (255, 128, 0)
FONT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "seguibli.ttf")   # Segoe UI Black Italic


def skylines(elev):
    """Elevation angle of the skyline (degrees) for each band of distance, across the view."""
    cell = SIZE / elev.shape[0]
    bearing = math.atan2(TARGET[0] - VIEW[0], TARGET[1] - VIEW[1])
    az = bearing + np.radians(np.linspace(-FOV / 2, FOV / 2, 1600))
    dist = np.geomspace(60.0, BANDS[-1], 2500)
    xs = VIEW[0] + np.sin(az)[:, None] * dist[None, :]
    zs = VIEW[1] + np.cos(az)[:, None] * dist[None, :]
    inside = (xs > 0) & (xs < SIZE - cell) & (zs > 0) & (zs < SIZE - cell)
    u, v = np.clip(xs / cell, 0, elev.shape[1] - 1.001), np.clip(zs / cell, 0, elev.shape[0] - 1.001)
    i, j = v.astype(int), u.astype(int)
    fu, fv = u - j, v - i
    h = (elev[i, j] * (1 - fu) * (1 - fv) + elev[i, j + 1] * fu * (1 - fv)
         + elev[i + 1, j] * (1 - fu) * fv + elev[i + 1, j + 1] * fu * fv)
    h = h - dist[None, :] ** 2 / (2 * 6371000.0) * 0.87          # earth curvature and refraction
    eye = float(elev[int(VIEW[1] / cell), int(VIEW[0] / cell)]) + 40.0
    ang = np.degrees(np.arctan2(h - eye, dist[None, :]))
    ang[~inside] = -90.0
    return [np.max(np.where(dist[None, :] <= band, ang, -90.0), axis=1) for band in BANDS]


def mix(a, b, t):
    return tuple(int(round(a[k] + (b[k] - a[k]) * t)) for k in range(3))


def emblem(lines):
    """The oval's picture in colour (RGBA, transparent outside the oval) and its outline."""
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sky = np.zeros((N, N, 4), np.uint8)
    top, bottom = CY - RY, CY + RY
    for y in range(N):
        t = np.clip((y - top) / (0.62 * (bottom - top)), 0, 1)
        sky[y, :, :3] = mix(SKY_TOP, SKY_LOW, t ** 1.4)
    sky[..., 3] = 255
    img = Image.fromarray(sky, "RGBA")
    # Each band's skyline keeps its own shape but gets its own height band: the far
    # skyline (Le Conte's massif) tallest and highest, nearer ridges lower and flatter,
    # each fading into mist at its foot.
    xs = np.linspace(CX - RX - 8, CX + RX + 8, len(lines[0]))
    rows = np.arange(N, dtype=np.float32)[:, None]
    d = ImageDraw.Draw(img)
    rnd = random.Random(7)
    far = len(lines) - 1
    for k in range(far, -1, -1):                                # far to near
        t = 1 - k / far
        colour = np.array(mix(RIDGE_FAR, RIDGE_NEAR, t ** 0.85), np.float32)
        p = np.convolve(np.maximum(lines[k], lines[k].max() - 12), np.ones(9) / 9, mode="same")
        p = (p - p.min()) / max(p.max() - p.min(), 1e-6)
        base = CY + RY * (-0.04 + 0.12 * (far - k))
        amp = RY * (0.66 if k == far else 0.30 - 0.03 * (far - 1 - k))
        ys = base - p * amp
        mask = Image.new("L", (N, N), 0)
        ImageDraw.Draw(mask).polygon([(float(x), float(y)) for x, y in zip(xs, ys)]
                                     + [(CX + RX + 8, N), (CX - RX - 8, N)], fill=255)
        crest = float(ys.min())
        fog = np.clip((rows - crest) / max(base + RY * 0.12 - crest, 1.0), 0, 1) ** 1.6 * (0.0 if k == 0 else 0.38 if k == far else 0.55)
        layer = colour[None, None, :] * (1 - fog[..., None]) + np.array(MIST, np.float32) * fog[..., None]
        layer = np.repeat(layer, N, axis=1)
        img = Image.composite(Image.fromarray(np.dstack([layer.astype(np.uint8),
                                                         np.full((N, N), 255, np.uint8)]), "RGBA"), img, mask)
        d = ImageDraw.Draw(img)
        if k == 0:                                              # spruces along the nearest ridge
            x = CX - RX - 20
            while x < CX + RX + 20:
                y0 = float(np.interp(x, xs, ys)) + 6
                hgt = rnd.uniform(70, 170)
                wid = hgt * rnd.uniform(0.30, 0.38)
                tiers = 4
                for q in range(tiers):
                    ty = y0 - hgt * q / tiers * 0.85
                    tw = wid * (1 - q / (tiers + 0.6))
                    d.polygon([(x - tw / 2, ty), (x + tw / 2, ty), (x, ty - hgt / tiers * 1.7)], fill=TREE + (255,))
                d.rectangle((x - 4, y0 - 4, x + 4, y0 + 30), fill=TREE + (255,))
                x += rnd.uniform(18, 46)
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).ellipse((CX - RX, CY - RY, CX + RX, CY + RY), fill=255)
    out = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    ring = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((CX - RX, CY - RY, CX + RX, CY + RY), outline=(0, 0, 0, 255), width=22)
    out.alpha_composite(ring)
    return out


def lettering(fill):
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for text, size, y in (("GREAT SMOKY", 210, 1385), ("MOUNTAINS", 300, 1650)):
        f = ImageFont.truetype(FONT, size)
        while d.textlength(text, font=f) > N - 2 * FRAME - 140:
            size -= 6
            f = ImageFont.truetype(FONT, size)
        d.text((N / 2, y), text, font=f, fill=fill + (255,), anchor="ms", stroke_width=18, stroke_fill=(0, 0, 0, 255))
    return img


def logo(colour_emblem, text_fill, frame, grey):
    em = colour_emblem
    if grey:
        r, g, b, a = em.split()
        lum = Image.merge("RGB", (r, g, b)).convert("L")
        lum = lum.point(lambda v: int(40 + v * 0.82))                # keep the darks off pure black
        em = Image.merge("RGBA", (lum, lum, lum, a))
        ring = Image.new("RGBA", (N, N), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((CX - RX, CY - RY, CX + RX, CY + RY), outline=(0, 0, 0, 255), width=22)
        em.alpha_composite(ring)
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    img.alpha_composite(em)
    img.alpha_composite(lettering(text_fill))
    border = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(border).rectangle((0, 0, N - 1, N - 1), outline=frame + (255,), width=FRAME)
    img.alpha_composite(border)
    return img.resize((N // 2, N // 2), Image.LANCZOS)


def main():
    elev_path, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    elev = np.load(elev_path)
    em = emblem(skylines(elev))
    files = {"logo": logo(em, (255, 255, 255), (0, 0, 0), True),
             "logo_hover": logo(em, TEXT_HOVER, HOVER_FRAME, False)}
    for name, im in files.items():
        im.save(os.path.join(out, name + ".png"))
        print("wrote", os.path.join(out, name + ".png"))
    if len(sys.argv) > 4:
        paa_dir, i2p = sys.argv[3], sys.argv[4]
        os.makedirs(paa_dir, exist_ok=True)
        for name in files:
            dst = os.path.join(paa_dir, name + ".paa")
            subprocess.run([i2p, os.path.join(out, name + ".png"), dst], capture_output=True, timeout=120)
            if not os.path.isfile(dst):
                sys.exit("ImageToPAA failed on " + name)
            print("wrote", dst)


if __name__ == "__main__":
    main()
