"""Make the OutsideTerrain satellite (CfgWorlds >> OutsideTerrain >> satellite): a seamless
1024 px colour tile of the forest at the map's edges, like vanilla's outside_sat_co
(Chernarus, 512 px) and enoch_satout_co (Livonia, 1024 px).

    python tools/outside_sat.py source source/terrain [<paa folder> <ImageToPAA.exe>]

Writes into <png folder>:
  outside_sat_co.png          1024 x 1024 RGB, the image ImageToPAA converts (DXT1, _co)
  outside_sat_preview.png     the tile repeated 2 x 2 at half size, to check the seams
and with a paa folder (data/ in the addon), outside_sat_co.paa there.

Six 2048 m squares of source/satellite.png near the map's edges, all forest with no
roads, fields or lots in source/mask.png (found once, listed in WINDOWS), are taken at
2 m per pixel. Each has its hill shading evened out (brightness divided by its 24 m
blur, to the power 0.85; colour kept), is made periodic (Moisan's periodic component)
and given a random phase (random-phase noise: one random phase for all three channels,
so the colours keep their relationships). The six are summed, which keeps their average
spectrum: crowns as speckle, evergreen and hardwood patches as soft blotches, no
recognisable shapes to repeat, and seamless by construction. Wavelengths over a third of
the tile are faded out. The tile gets the six squares' mean colour (the forest along the
edge: brown-grey, a little green) and a brightness spread of 7 (std of the RGB mean),
about vanilla Chernarus's.
"""

import os
import subprocess
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

SIZE = 20480                         # satellite.png, 1 m per pixel, north up
N = 1024                             # output tile
STEP = 2                             # metres per output pixel
WINDOWS = [                          # south-west corners (x, z) of 2048 m squares of edge forest
    (17856, 13312),                  # east edge, north
    (17344, 3840),                   # east edge, south
    (14336, 9472),                   # east, inland of the edge
    (1280, 4864),                    # west edge
    (2944, 2048),                    # south-west
    (6208, 3072),                    # south edge
]
FLAT_SIGMA, FLAT_POWER = 12, 0.85    # hill shading: blur (px) and how much is removed
LOW_CUT = 3.0                        # cycles per tile below which wavelengths fade out
LUM_STD = 7.0
SEED = 20480


def flatten(img):
    lum = img.mean(-1)
    low = ndimage.gaussian_filter(lum, FLAT_SIGMA, mode="reflect")
    return img * ((lum.mean() / np.maximum(low, 1.0)) ** FLAT_POWER)[..., None]


def periodic(u):
    """Moisan's periodic + smooth decomposition: the periodic part of one channel."""
    h, w = u.shape
    v = np.zeros_like(u)
    v[0, :] += u[-1, :] - u[0, :]
    v[-1, :] += u[0, :] - u[-1, :]
    v[:, 0] += u[:, -1] - u[:, 0]
    v[:, -1] += u[:, 0] - u[:, -1]
    q = np.arange(h)[:, None]
    r = np.arange(w)[None, :]
    den = 2 * np.cos(2 * np.pi * q / h) + 2 * np.cos(2 * np.pi * r / w) - 4
    den[0, 0] = 1.0
    s = np.fft.fft2(v) / den
    s[0, 0] = 0.0
    return u - np.real(np.fft.ifft2(s))


def random_phase(img, rng, gain):
    phase = np.exp(1j * np.angle(np.fft.fft2(rng.standard_normal(img.shape[:2]))))
    out = np.empty_like(img)
    for c in range(img.shape[2]):
        f = np.fft.fft2(img[..., c] - img[..., c].mean())
        out[..., c] = np.real(np.fft.ifft2(f * phase * gain))
    return out


def main():
    if len(sys.argv) not in (3, 5):
        sys.exit(__doc__)
    src, png_dir = sys.argv[1], sys.argv[2]
    os.makedirs(png_dir, exist_ok=True)
    sat = Image.open(os.path.join(src, "satellite.png"))
    if sat.size != (SIZE, SIZE):
        sys.exit("satellite.png is %dx%d, expected %d" % (sat.size + (SIZE,)))
    sat.load()

    k = np.hypot(np.fft.fftfreq(N)[:, None], np.fft.fftfreq(N)[None, :]) * N
    gain = 1.0 - np.exp(-(k / LOW_CUT) ** 2)
    rng = np.random.default_rng(SEED)
    means, acc = [], np.zeros((N, N, 3))
    side = N * STEP
    for x0, z0 in WINDOWS:
        top = SIZE - z0 - side
        crop = sat.crop((x0, top, x0 + side, top + side)).convert("RGB")
        a = np.asarray(crop.resize((N, N), Image.Resampling.BOX)).astype(np.float64)
        means.append(a.reshape(-1, 3).mean(0))
        a = flatten(a)
        a = np.dstack([periodic(a[..., c]) for c in range(3)])
        acc += random_phase(a, rng, gain)
        print("x %5d..%5d  z %5d..%5d  mean RGB %s" % (x0, x0 + side, z0, z0 + side, np.round(means[-1], 1)))
    del sat
    acc /= np.sqrt(len(WINDOWS))
    mean = np.mean(means, axis=0)
    tile = mean + acc * (LUM_STD / acc.mean(-1).std())
    rgb = np.clip(np.floor(tile + 0.5), 0, 255).astype(np.uint8)

    png = os.path.join(png_dir, "outside_sat_co.png")
    Image.fromarray(rgb).save(png)
    Image.fromarray(np.tile(rgb, (2, 2, 1))).resize((N, N), Image.Resampling.BOX).save(
        os.path.join(png_dir, "outside_sat_preview.png"))
    print("%s: %dx%d, mean RGB %s, std %s" % (png, N, N, np.round(rgb.reshape(-1, 3).mean(0), 1),
                                              np.round(rgb.reshape(-1, 3).std(0), 1)))
    if len(sys.argv) == 5:
        paa_dir, exe = sys.argv[3], sys.argv[4]
        os.makedirs(paa_dir, exist_ok=True)
        paa = os.path.join(paa_dir, "outside_sat_co.paa")
        if os.path.exists(paa):
            os.remove(paa)
        run = subprocess.run([exe, png, paa], capture_output=True, text=True, errors="replace")
        if not os.path.isfile(paa):
            sys.exit("ImageToPAA failed: %s" % (run.stdout + run.stderr).strip()[-300:])
        print("%s: %d bytes" % (paa, os.path.getsize(paa)))


if __name__ == "__main__":
    main()
