"""National Park Service style trail signs: a brown post with a routed board, the
board's face a texture of what the sign says. tools/details.py decides where the
signs stand and what they say, and calls make_sign() for each.

    make_sign(name, title, rows, model_dir, png_dir, i2p) -> template name

title is the trail name(s) across the top; rows are (arrow, place, miles) with
arrow one of "", "left", "right", "ahead". Writes <png_dir>/<name>_co.png (kept
with the sources), <model_dir>/<name>_co.paa (via DayZ Tools' ImageToPAA) and
<model_dir>/<name>.p3d (MLOD, binarized with the map like the SkyBridge).

The model: a 12 cm post from 30 cm under the ground to 2 m, and a 1.2 x 0.6 m
board, 5 cm thick, on its front at 1.25 to 1.85 m. The board's front looks along
the model's +z: place a sign with its yaw pointing from the sign to the reader.
LODs as the SkyBridge's (tools/skybridge.py): visual, Geometry with mass
(autocenter 0, the origin at the foot of the post), View and Fire Geometry (wood).
"""

import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import mlod
from skybridge import Lod, PEN, box, prop

WOOD = r"dz\structures\data\wood\wood_brown_co.paa"
TEX_W, TEX_H = 1024, 512
BOARD_W, BOARD_H, BOARD_T = 1.2, 0.6, 0.05
BOARD_Y = 1.55                               # board centre above the ground
POST_HALF, POST_TOP, POST_FOOT = 0.06, 2.0, -0.3
BROWN, GROOVE, LETTER, SHADE = (84, 56, 36), (52, 34, 22), (238, 226, 196), (36, 22, 14)
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
PREFIX = "greatsmokymountains"


def font(size, bold=True):
    return ImageFont.truetype(os.path.join(FONT_DIR, "ROCKB.TTF" if bold else "ROCK.TTF"), size)


def fit(d, text, start, width, bold=True):
    """The largest font from start down whose text fits the width."""
    size = start
    while size > 18 and d.textlength(text, font=font(size, bold)) > width:
        size -= 2
    return font(size, bold)


def arrow(d, x, y, size, way, fill):
    """A routed arrow centred at (x, y) pointing left, right or ahead (up)."""
    s = size / 2
    shapes = {"right": [(-s, -s * 0.28), (s * 0.2, -s * 0.28), (s * 0.2, -s * 0.7), (s, 0), (s * 0.2, s * 0.7),
                        (s * 0.2, s * 0.28), (-s, s * 0.28)]}
    shapes["left"] = [(-px, py) for px, py in shapes["right"]]
    shapes["ahead"] = [(py, -px) for px, py in shapes["right"]]
    d.polygon([(x + px, y + py) for px, py in shapes[way]], fill=fill)


def texture(title, rows, seed):
    """The board's face: brown wood, a routed border, the title and the rows."""
    rng = np.random.default_rng(seed)
    grain = np.full((TEX_H, TEX_W, 3), BROWN, np.float32)
    lines = np.cumsum(rng.normal(0, 1.2, (TEX_H, 1)), axis=0) % 9                  # wood grain, along the board
    grain *= (0.92 + 0.08 * np.sin(lines + np.linspace(0, 6, TEX_W)[None, :] * rng.uniform(0.5, 1.5)))[..., None]
    grain *= rng.uniform(0.95, 1.05, (TEX_H, TEX_W, 1))
    img = Image.fromarray(np.clip(grain, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((22, 22, TEX_W - 23, TEX_H - 23), radius=26, outline=GROOVE, width=7)

    def routed(xy, text, f, anchor):
        d.text((xy[0] + 3, xy[1] + 3), text, font=f, fill=SHADE, anchor=anchor)
        d.text(xy, text, font=f, fill=LETTER, anchor=anchor)
    y = 70
    if title:
        f = fit(d, title, 76, TEX_W - 120)
        if f.size < 46 and " / " in title:                 # two trails' names: a line each
            a, b = title.split(" / ", 1)
            f = min(fit(d, a, 56, TEX_W - 120), fit(d, b, 56, TEX_W - 120), key=lambda f: f.size)
            routed((TEX_W / 2, y - 12), a, f, "mm")
            routed((TEX_W / 2, y + f.size - 8), b, f, "mm")
            y += f.size
        else:
            routed((TEX_W / 2, y), title, f, "mm")
        y += 66
        d.line((70, y - 8, TEX_W - 70, y - 8), fill=GROOVE, width=5)
    n = max(1, len(rows))
    step = min(88, (TEX_H - 50 - y) / n)
    size = int(min(64, step * 0.78))
    for k, (way, place, miles) in enumerate(rows):
        cy = y + step * (k + 0.5)
        x0 = 70
        if way:
            arrow(d, x0 + 3 + size * 0.45, cy + 3, size * 0.9, way, SHADE)
            arrow(d, x0 + size * 0.45, cy, size * 0.9, way, LETTER)
            x0 += int(size * 1.1)
        mtxt = "%.1f" % miles if miles is not None else ""
        mw = d.textlength(mtxt, font=font(size)) if mtxt else 0
        f = fit(d, place, size, TEX_W - 70 - x0 - mw - 40)
        routed((x0, cy), place, f, "lm")
        if mtxt:
            routed((TEX_W - 70, cy), mtxt, font(size), "rm")
    return img


def model(tex_path):
    vis, geom, view, fire = Lod(1.0), Lod(1e13), Lod(6e15), Lod(7e15)
    post = box(0.0, (POST_TOP + POST_FOOT) / 2, 0.0, POST_HALF, (POST_TOP - POST_FOOT) / 2, POST_HALF)
    z0, z1 = POST_HALF, POST_HALF + BOARD_T
    hw, hh = BOARD_W / 2, BOARD_H / 2
    board = box(0.0, BOARD_Y, (z0 + z1) / 2, hw, hh, BOARD_T / 2)
    vis.solid(post, WOOD, uv_scale=1.0)
    # The board: its front carries the texture, read from +z (the reader's right is the model's -x).
    yt, yb = BOARD_Y + hh, BOARD_Y - hh
    vis.face([(hw, yt, z1), (-hw, yt, z1), (-hw, yb, z1), (hw, yb, z1)], [(0, 0), (1, 0), (1, 1), (0, 1)],
             tex_path, out=(0, 0, 1))
    vis.face([(-hw, yt, z0), (hw, yt, z0), (hw, yb, z0), (-hw, yb, z0)], [(0, 0), (1, 0), (1, 0.5), (0, 0.5)],
             WOOD, out=(0, 0, -1))
    for corners, out in (([(-hw, yt, z0), (-hw, yt, z1), (hw, yt, z1), (hw, yt, z0)], (0, 1, 0)),
                         ([(-hw, yb, z0), (hw, yb, z0), (hw, yb, z1), (-hw, yb, z1)], (0, -1, 0)),
                         ([(hw, yb, z0), (hw, yt, z0), (hw, yt, z1), (hw, yb, z1)], (1, 0, 0)),
                         ([(-hw, yb, z0), (-hw, yb, z1), (-hw, yt, z1), (-hw, yt, z0)], (-1, 0, 0))):
        vis.face(corners, [(0, 0), (0.05, 0), (0.05, 0.6), (0, 0.6)], WOOD, out=out)
    for k, (corners, mass) in enumerate(((post, 25.0), (board, 15.0))):
        sel = "Component%02d" % (k + 1)
        geom.solid(corners, sel=sel, mass=mass)
        view.solid(corners, sel=sel)
        fire.solid(corners, mat=PEN["wood"], sel=sel)
    geom.props = [prop("autocenter", "0")]
    return dict(version=257, lods=[vis.to_mlod(), geom.to_mlod(), view.to_mlod(), fire.to_mlod()])


def make_sign(name, title, rows, model_dir, png_dir, i2p, seed=0):
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(png_dir, exist_ok=True)
    png = os.path.join(png_dir, name + "_co.png")
    texture(title, rows, seed).save(png)
    paa = os.path.join(model_dir, name + "_co.paa")
    if i2p and os.path.isfile(i2p):
        if os.path.isfile(paa):
            os.remove(paa)
        subprocess.run([i2p, png, paa], capture_output=True, timeout=120)
        if not os.path.isfile(paa):
            raise SystemExit("ImageToPAA failed on " + png)
    rel = os.path.relpath(model_dir, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tex = "\\".join([PREFIX] + rel.replace("/", "\\").split("\\") + [name + "_co.paa"])
    path = os.path.join(model_dir, name + ".p3d")
    mlod.write(model(tex), path)
    assert len(mlod.read(path)["lods"]) == 4
    return name
