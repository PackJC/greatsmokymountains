"""Find where the map sits in UTM 17N by matching its heightmap to real elevations.

    python tools/georef.py smokymountains.wrp <first guess json> <dem tile folder> tools/georef.json [zoom] [stride]

The first guess gives map = UTM + (tx, ty) at true scale with no rotation. This
samples AWS Terrain Tiles (Terrarium, zoom 13 by default, every stride-th pixel),
maps each DEM pixel into the map, and searches the offset that best matches the heights.
"""

import json
import math
import os
import sys
import urllib.request

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import utm  # noqa: E402
from oprw import OPRW  # noqa: E402

ZOOM = 13
URL = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/%d/%d/%d.png"
UA = "greatsmokymountains-dayz-map/1.0"


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def pixel_latlon(tx, ty, px, py, z):
    n = 2 ** z
    x = (tx + (px + 0.5) / 256) / n
    y = (ty + (py + 0.5) / 256) / n
    lon = x * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))
    return lat, lon


def fetch(folder, x, y):
    path = os.path.join(folder, "%d_%d_%d.png" % (ZOOM, x, y))
    if not os.path.isfile(path):
        req = urllib.request.Request(URL % (ZOOM, x, y), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as fh:
            fh.write(r.read())
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


def bilinear(grid, x, y):
    x0 = np.clip(np.floor(x).astype(int), 0, grid.shape[1] - 2)
    y0 = np.clip(np.floor(y).astype(int), 0, grid.shape[0] - 2)
    fx, fy = x - x0, y - y0
    return (grid[y0, x0] * (1 - fx) * (1 - fy) + grid[y0, x0 + 1] * fx * (1 - fy)
            + grid[y0 + 1, x0] * (1 - fx) * fy + grid[y0 + 1, x0 + 1] * fx * fy)


def main():
    global ZOOM
    wrp, fit_path, folder, out = sys.argv[1:5]
    if len(sys.argv) > 5:
        ZOOM = int(sys.argv[5])
    stride = int(sys.argv[6]) if len(sys.argv) > 6 else 2
    os.makedirs(folder, exist_ok=True)
    fit = json.load(open(fit_path))
    w = OPRW(wrp)
    cell = w.terrain_cell
    elev = np.frombuffer(w.elevation, "<f4").reshape(w.terrain_y, w.terrain_x).astype(np.float64)
    size = w.terrain_x * cell

    # Offset so that map = UTM + (ox, oy), starting from the first guess: a peak fit
    # ({"tx", "ty", "scale", "theta", "rms"}) or an earlier tools/georef.json.
    ox, oy = (fit["tx"], fit["ty"]) if "tx" in fit else (fit["offset_x"], fit["offset_y"])

    # Lat/lon box of the map: walk out from a known point with a local metres-per-degree.
    lat0, lon0 = 35.65426, -83.43683                       # Mt Le Conte, for the box only
    ex, ny = utm(lat0, lon0, 17)
    mx, my = ex + ox, ny + oy
    mlat, mlon = 111132.0, 111320.0 * math.cos(math.radians(lat0))
    lat_lo, lat_hi = lat0 - (my + 600) / mlat, lat0 + (size - my + 600) / mlat
    lon_lo, lon_hi = lon0 - (mx + 600) / mlon, lon0 + (size - mx + 600) / mlon
    x_lo, y_hi = tile_xy(lat_lo, lon_lo, ZOOM)
    x_hi, y_lo = tile_xy(lat_hi, lon_hi, ZOOM)

    pts_e, pts_n, hts = [], [], []
    for ty in range(int(y_lo), int(y_hi) + 1):
        for tx in range(int(x_lo), int(x_hi) + 1):
            dem = fetch(folder, tx, ty)
            for py in range(0, 256, stride):
                for px in range(0, 256, stride):
                    la, lo = pixel_latlon(tx, ty, px, py, ZOOM)
                    e, n = utm(la, lo, 17)
                    pts_e.append(e)
                    pts_n.append(n)
                    hts.append(dem[py, px])
    pts_e, pts_n, hts = np.array(pts_e), np.array(pts_n), np.array(hts)
    print("DEM samples: %d" % len(hts))

    def cost(dx, dy):
        x = (pts_e + dx) / cell
        y = (pts_n + dy) / cell
        inside = (x > 2) & (x < w.terrain_x - 3) & (y > 2) & (y < w.terrain_y - 3)
        d = bilinear(elev, x[inside], y[inside]) - hts[inside]
        d -= np.median(d)                                  # allow a constant height datum offset
        return float(np.sqrt((d ** 2).mean())), int(inside.sum())

    best = (cost(ox, oy)[0], ox, oy)
    for step in (16.0, 4.0, 1.0, 0.25):
        improved = True
        while improved:
            improved = False
            for ddx in (-step, 0, step):
                for ddy in (-step, 0, step):
                    c = cost(best[1] + ddx, best[2] + ddy)[0]
                    if c < best[0] - 1e-6:
                        best = (c, best[1] + ddx, best[2] + ddy)
                        improved = True
    rms, n_in = cost(best[1], best[2])
    x = (pts_e + best[1]) / cell
    y = (pts_n + best[2]) / cell
    inside = (x > 2) & (x < w.terrain_x - 3) & (y > 2) & (y < w.terrain_y - 3)
    datum = float(np.median(bilinear(elev, x[inside], y[inside]) - hts[inside]))

    result = {
        "projection": "WGS 84 / UTM zone 17N (EPSG:32617)",
        "map_x = utm_easting + offset_x": best[1],
        "map_z = utm_northing + offset_y": best[2],
        "offset_x": best[1], "offset_y": best[2],
        "map_origin_utm_easting": -best[1], "map_origin_utm_northing": -best[2],
        "scale": 1.0, "rotation_deg": 0.0,
        "height_rms_vs_dem_m": rms, "height_datum_map_minus_dem_m": datum, "dem_samples_used": n_in,
        "dem": "AWS Terrain Tiles (Terrarium), zoom %d" % ZOOM,
        # The peak fit only confirms true scale and no rotation; its own translation is taken
        # about the UTM origin, so it is a first guess for the search above, not a result.
        "peak_fit": fit["peak_fit"] if "peak_fit" in fit else
        {"scale": fit["scale"], "rotation_deg": math.degrees(fit["theta"]), "rms_m": fit["rms"]},
    }
    json.dump(result, open(out, "w"), indent=2)
    print("first guess      %.1f, %.1f" % (ox, oy))
    print("DEM fit offset   %.2f, %.2f  (moved %.1f m)" % (best[1], best[2], math.hypot(best[1] - ox, best[2] - oy)))
    print("height rms vs DEM %.2f m over %d samples, datum %.2f m" % (rms, n_in, datum))
    print("map SW corner = UTM 17N %.1f E, %.1f N" % (-best[1], -best[2]))


if __name__ == "__main__":
    main()
