"""Bounding boxes of a binarized model's levels of detail, e.g. the roadway (deck).

    python tools/odol_lods.py <model.p3d> ...

Finds the LOD start/end address tables (two ascending runs of n file offsets,
each LOD ending where the next starts) instead of parsing the whole header,
then reads each LOD's own box. With no proxies or skeleton, a LOD starts:
proxy count, two empty skeleton maps, vertex count, face area, or/and hints,
box min, box max (BIS ODOL, version 50 and up).
"""

import os
import struct
import sys

NAMES = {0.0: "visual", 1e13: "shadow/geometry", 1e15: "memory", 2e15: "landcontact", 3e15: "roadway",
         4e15: "paths", 5e15: "hitpoints", 6e15: "viewgeometry", 7e15: "firegeometry"}


def lod_name(res):
    for k, v in NAMES.items():
        if k and abs(res - k) < k * 1e-4:
            return v
    return "visual %g" % res if res < 1e4 else "%g" % res


def lod_boxes(path):
    d = open(path, "rb").read()
    version, n = struct.unpack_from("<2i", d, 4)
    res = struct.unpack_from("<%df" % n, d, 12)
    size = len(d)
    for p in range(12 + 4 * n, len(d) - 8 * n, 4):
        starts = struct.unpack_from("<%dI" % n, d, p)
        ends = struct.unpack_from("<%dI" % n, d, p + 4 * n)
        if not all(0 < s < e <= size for s, e in zip(starts, ends)):
            continue
        if any(starts[k + 1] < ends[k] for k in range(n - 1)) or starts[0] < p:
            continue
        out = []
        for r, s, e in zip(res, starts, ends):
            nprox = struct.unpack_from("<i", d, s)[0]
            if nprox != 0:
                out.append((lod_name(r), None, "has %d proxies" % nprox))
                continue
            q = s + 4
            q += 4 + 4 * struct.unpack_from("<i", d, q)[0]           # sub-skeleton to skeleton
            q += 4 + 4 * struct.unpack_from("<i", d, q)[0]           # skeleton to sub-skeleton (empty)
            q += 8                                                   # vertex count, face area
            q += 8                                                   # or/and hints
            mn = struct.unpack_from("<3f", d, q)
            mx = struct.unpack_from("<3f", d, q + 12)
            out.append((lod_name(r), (mn, mx), ""))
        return version, out
    return version, None


def main():
    for f in sys.argv[1:]:
        version, lods = lod_boxes(f)
        print("== %s (v%d)" % (os.path.basename(f), version))
        if lods is None:
            print("   LOD tables not found")
            continue
        for name, box, note in lods:
            if box:
                (a, b, c), (x, y, z) = box
                print("   %-16s y %7.2f..%7.2f  x %7.2f..%7.2f  z %7.2f..%7.2f" % (name, b, y, a, x, c, z))
            else:
                print("   %-16s %s" % (name, note))


if __name__ == "__main__":
    main()
