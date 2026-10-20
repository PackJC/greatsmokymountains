"""Read the placement facts of binarized (ODOL) models from their headers.

    python tools/odol_info.py <folder or .p3d> ...

For each model: bounding box (in the model's binarized space, whose origin is
where an object's position puts it), the bounding centre (where that origin
sits in the original model, so its own origin is at minus this), and the
auto-centre flag. Field order is BIS ModelInfo (bboxMinVisual/MaxVisual from
version 52).
"""

import glob
import os
import struct
import sys


def odol_info(path):
    with open(path, "rb") as fh:
        d = fh.read(512)
    if d[:4] != b"ODOL":
        return None
    version, n = struct.unpack_from("<2i", d, 4)
    p = 12 + 4 * n                                     # ModelInfo
    q = p + 48                                         # after special..viewDensity, aimingCenter
    if version >= 70:
        q += 4
    if version >= 71:
        q += 4
    mn = struct.unpack_from("<3f", d, p + 48)
    mx = struct.unpack_from("<3f", d, p + 60)
    off = p + 72 + (24 if version >= 52 else 0) + (4 if version >= 70 else 0) + (4 if version >= 71 else 0)
    bc = struct.unpack_from("<3f", d, off)
    auto = d[off + 12 * 3 + 36]
    return {"version": version, "min": mn, "max": mx, "center": bc, "autocenter": auto}


def main():
    files = []
    for a in sys.argv[1:]:
        files += sorted(glob.glob(os.path.join(a, "**", "*.p3d"), recursive=True)) if os.path.isdir(a) else [a]
    for f in files:
        i = odol_info(f)
        if not i:
            continue
        print("%-34s y %6.2f..%6.2f  x %6.2f..%6.2f  centre %6.2f %6.2f %6.2f  auto %d"
              % (os.path.basename(f)[:-4][:34], i["min"][1], i["max"][1], i["min"][0], i["max"][0],
                 *i["center"], i["autocenter"]))


if __name__ == "__main__":
    main()
