"""Make the map's terrain-wide normal map (CfgWorlds terrainNormalTexture), encoded
exactly like vanilla's global_nohq.paa (Chernarus) and enoch_global_nohq.paa (Livonia).

    python tools/global_normal.py [--exact] source/buildings/elevation.npy source/terrain [<paa folder> <ImageToPAA.exe>]

Writes into <png folder>:
  global_nohq.png          2048 x 2048 (10 m per pixel), the image ImageToPAA converts
  global_nohq_preview.png  north up, 2 x 512 px: the normal map, and the relief it shades
and with a paa folder (data/ in the addon), global_nohq.paa there.

The encoding, fitted to the vanilla textures against the vanilla worlds' own heights
(Livonia 2048 px on its 2048 grid: r = 0.983 for X, 0.978 for Y; Chernarus 1024 px on
its 2048 grid: r = 0.976 / 0.973, the rest being terrain edited after the maps were made):
  - the unit surface normal from central differences of the heights at the texture's
    own spacing; for a smaller texture than the grid, the heights are box-averaged
    down first (as Chernarus's 1024 px is from its 2048 grid). No smoothing.
  - red   = 127.5 + 127.5 * east component  (east-facing slopes red)
    green = 127.5 + 127.5 * north component (north-facing slopes green)
    blue  = 0, no alpha. Full strength (fitted scale 0.98 to 1.01).
  - rows run south to north: the first row is the south edge, so the image looks
    upside down (north at the bottom), as vanilla's does.
ImageToPAA (the _nohq suffix) makes DXT5 with the channels swizzled (alpha = 1 - red,
red = 0, green kept; tag SWIZ 05 04 02 03), as vanilla's are; converting back to PNG
undoes the swizzle. Vanilla's small blue values are DXT noise from a blue of 0.

ImageToPAA also renormalises every pixel as the vector (2r - 1, 2g - 1, 2b - 1), so a
blue of 0 counts as z = -1 and the stored slope is x / sqrt(1 + x^2 + y^2): a 20 deg
slope keeps 18.9 deg, 30 deg becomes 26.6, 45 deg becomes 35. Vanilla's terrain is
gentle (mean 0.3 deg lost); here it's steeper (mean 1.7 deg, 1 in 10 pixels over 4 deg).
The default copies vanilla regardless. --exact writes the height gradient (-dh/dx,
-dh/dz) instead of the normal's components, still with blue 0, so that after the
renormalisation the .paa holds the true unit normal (slopes over 45 deg along an
axis are clamped to it, keeping their direction; 0.2% of pixels).
"""

import os
import subprocess
import sys

import numpy as np
from PIL import Image

SIZE = 20480.0                       # terrain size, m
OUT = 2048                           # texture size (10 m per pixel, like Livonia and Sakhal)
PEAK = (10120.0, 7825.0)             # Mt. Le Conte (heightmap_info.txt): checks the row order


def load_heights(path):
    elev = np.load(path).astype(np.float64)
    n = elev.shape[0]
    cell = SIZE / n
    r, c = np.unravel_index(np.argmax(elev), elev.shape)
    if abs(c * cell - PEAK[0]) > cell or abs(r * cell - PEAK[1]) > cell:
        sys.exit("orientation check failed: highest point at x %.0f, z %.0f (row 0 = south), expected %s"
                 % (c * cell, r * cell, PEAK))
    print("heights %dx%d @ %g m, %.2f..%.2f m, peak %.2f m at x %.0f z %.0f (row 0 = south)"
          % (n, n, cell, elev.min(), elev.max(), elev[r, c], c * cell, r * cell))
    return elev


def normals(elev, out):
    n = elev.shape[0]
    f = n // out
    if f * out != n:
        sys.exit("grid %d is not a multiple of %d" % (n, out))
    h = elev.reshape(out, f, out, f).mean(axis=(1, 3)) if f > 1 else elev
    spacing = SIZE / out
    dz, dx = np.gradient(h, spacing)             # rows go north, columns east
    length = np.sqrt(dx * dx + dz * dz + 1.0)
    return -dx / length, -dz / length, 1.0 / length


def encode(nx, nz, ny, exact=False):
    if exact:                                    # the gradient: ImageToPAA's renormalisation
        nx, nz = nx / ny, nz / ny                # turns (gx, gz, -1) back into the unit normal
        over = np.maximum(1.0, np.maximum(np.abs(nx), np.abs(nz)))
        nx, nz = nx / over, nz / over

    def chan(v):
        return np.clip(np.floor(127.5 + 127.5 * v + 0.5), 0, 255).astype(np.uint8)
    return np.dstack([chan(nx), chan(nz), np.zeros(nx.shape, np.uint8)])


def preview(rgb, path, size=512):
    """North up: the normal map beside the relief it shades (sun from the north-west, 45 deg up),
    as the .paa will hold it (after ImageToPAA's renormalisation, z rebuilt from x and y)."""
    a = rgb.astype(np.float64)
    nx, nz, nb = a[..., 0] / 127.5 - 1.0, a[..., 1] / 127.5 - 1.0, a[..., 2] / 127.5 - 1.0
    length = np.sqrt(nx * nx + nz * nz + nb * nb)
    nx, nz = nx / length, nz / length
    ny = np.sqrt(np.clip(1.0 - nx * nx - nz * nz, 0.0, 1.0))
    sun = np.array([-0.5, 0.5, np.sqrt(0.5)])    # east, north, up
    shade = np.clip(nx * sun[0] + nz * sun[1] + ny * sun[2], 0.0, 1.0)
    grey = np.round(255.0 * (0.2 + 0.8 * shade)).astype(np.uint8)
    left = Image.fromarray(rgb[::-1]).resize((size, size), Image.Resampling.BOX)
    right = Image.fromarray(np.dstack([grey[::-1]] * 3)).resize((size, size), Image.Resampling.BOX)
    sheet = Image.new("RGB", (2 * size, size))
    sheet.paste(left, (0, 0))
    sheet.paste(right, (size, 0))
    sheet.save(path)


def main():
    args = [a for a in sys.argv[1:] if a != "--exact"]
    exact = len(args) < len(sys.argv) - 1
    if len(args) not in (2, 4):
        sys.exit(__doc__)
    elev_path, png_dir = args[0], args[1]
    os.makedirs(png_dir, exist_ok=True)
    elev = load_heights(elev_path)
    nx, nz, ny = normals(elev, OUT)
    rgb = encode(nx, nz, ny, exact)
    png = os.path.join(png_dir, "global_nohq.png")
    Image.fromarray(rgb).save(png)
    preview(rgb, os.path.join(png_dir, "global_nohq_preview.png"))
    print("%s: %dx%d%s, red %.1f +- %.1f, green %.1f +- %.1f, steepest %.1f deg"
          % (png, OUT, OUT, " (--exact)" if exact else "", rgb[..., 0].mean(), rgb[..., 0].std(),
             rgb[..., 1].mean(), rgb[..., 1].std(), np.degrees(np.arccos(ny.min()))))
    if len(args) == 4:
        paa_dir, exe = args[2], args[3]
        os.makedirs(paa_dir, exist_ok=True)
        paa = os.path.join(paa_dir, "global_nohq.paa")
        if os.path.exists(paa):
            os.remove(paa)
        run = subprocess.run([exe, png, paa], capture_output=True, text=True, errors="replace")
        if not os.path.isfile(paa):
            sys.exit("ImageToPAA failed: %s" % (run.stdout + run.stderr).strip()[-300:])
        print("%s: %d bytes" % (paa, os.path.getsize(paa)))


if __name__ == "__main__":
    main()
