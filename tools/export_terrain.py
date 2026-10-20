"""Rebuild Terrain Builder heightmap sources from a binarized DayZ world.

    python tools/export_terrain.py source/original/smokymountains.wrp source [source/water/elevation.npy]

The optional .npy replaces the world's heights (e.g. with the creek channels
tools/osm_water.py carves); the world still supplies grid sizes and peaks.

Writes into <out>:
  heightmap.asc        ESRI ASCII grid for Terrain Builder (Import > Heightmap),
                       origin easting 200000 / northing 0, as Terrain Builder expects
  heightmap_16bit.png  the same heights scaled to 0..65535 (min/max in
                       heightmap_info.txt) for World Machine, Gaea, L3DT and the like
  heightmap_info.txt   grid size, cell size, height range and the PNG scaling
"""

import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oprw import OPRW  # noqa: E402

EASTING = 200000.0


def main():
    wrp_path, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    w = OPRW(wrp_path)
    if w.trailing:
        sys.exit("parse error: %d bytes left over at the end of the wrp" % w.trailing)

    n = w.terrain_x
    elev = np.frombuffer(w.elevation, "<f4").reshape(w.terrain_y, n)   # row 0 = south
    carved = len(sys.argv) > 3
    if carved:
        elev = np.load(sys.argv[3]).astype("<f4")

    # Check the orientation against the highest peak the wrp lists.
    px, py, pz = max(w.mountains, key=lambda m: m[1])
    got = elev[int(round(pz / w.terrain_cell)), int(round(px / w.terrain_cell))]
    if abs(got - py) > 0.05:                         # (summits are never carved)
        sys.exit("orientation check failed: peak %.2f at (%.0f, %.0f) but grid has %.2f" % (py, px, pz, got))

    north_up = elev[::-1]
    lo, hi = float(elev.min()), float(elev.max())

    with open(os.path.join(out, "heightmap.asc"), "w", newline="\n") as fh:
        fh.write("ncols         %d\n" % n)
        fh.write("nrows         %d\n" % w.terrain_y)
        fh.write("xllcorner     %.6f\n" % EASTING)
        fh.write("yllcorner     %.6f\n" % 0.0)
        fh.write("cellsize      %.6f\n" % w.terrain_cell)
        fh.write("NODATA_value  -9999\n")
        np.savetxt(fh, north_up, fmt="%.3f", delimiter=" ")

    scaled = np.round((north_up - lo) / (hi - lo) * 65535.0).astype("<u2")
    Image.fromarray(scaled).save(os.path.join(out, "heightmap_16bit.png"))

    size_m = n * w.terrain_cell
    with open(os.path.join(out, "heightmap_info.txt"), "w", newline="\n") as fh:
        fh.write("source            %s (OPRW v%d)%s\n" % (os.path.basename(wrp_path), w.version,
                                                        ", heights from %s" % sys.argv[3] if carved else ""))
        fh.write("terrain grid      %d x %d\n" % (n, w.terrain_y))
        fh.write("terrain cell size %g m\n" % w.terrain_cell)
        fh.write("terrain size      %g x %g m\n" % (size_m, w.terrain_y * w.terrain_cell))
        fh.write("layer grid        %d x %d, %g m cells\n" % (w.land_x, w.land_y, w.land_cell))
        fh.write("height min        %.3f m\n" % lo)
        fh.write("height max        %.3f m\n" % hi)
        fh.write("16-bit PNG        0 = %.3f m, 65535 = %.3f m (%.5f m per step)\n" % (lo, hi, (hi - lo) / 65535))
        fh.write("asc origin        easting %.0f, northing 0 (Terrain Builder mapframe default)\n" % EASTING)
        fh.write("highest peak      %.2f m at x %.0f, z %.0f\n" % (py, px, pz))
        fh.write("placed objects    %d\n" % len(w.objects))
        fh.write("road links        %d\n" % len(w.roads))

    if w.objects:
        print("note: %d placed objects found; object export is not written yet" % len(w.objects))

    print("OPRW v%d  %dx%d @ %g m  heights %.2f..%.2f m" % (w.version, n, w.terrain_y, w.terrain_cell, lo, hi))
    print("peak check ok: %.2f m at (%.0f, %.0f)" % (py, px, pz))
    print("objects %d, models %d, road links %d" % (len(w.objects), len(w.models), len(w.roads)))
    print("written to %s" % out)


if __name__ == "__main__":
    main()
