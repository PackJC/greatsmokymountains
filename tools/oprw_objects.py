"""Read the placed objects of an OPRW v32 world without unpacking its grids.

    python tools/oprw_objects.py <world.wrp> [model filter]

Current DayZ worlds compress their grids in a container tools/oprw.py doesn't
unpack, but the model list, the object block's size, the map-info block's size
and the object records are plain. The object block sits just before the map
info at the end of the file: 64-byte records (id, model index, 4x3 matrix,
shape param, one more int).
"""

import math
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oprw import Reader, QuadTree  # noqa: E402


def read_objects(path):
    d = open(path, "rb").read()
    version = struct.unpack_from("<i", d, 4)[0]
    record = 64 if version >= 32 else 60
    # Model list: an int32 count then NUL-terminated paths. Find a real model path
    # (compressed data can hold "dz\" by chance), then walk back to the count.
    m = re.search(rb"[dD][zZ]\\[\x20-\x7e]{3,200}?\.p3d\x00", d)
    s0 = m.start()
    while True:
        prev = d.rfind(b"\x00", 0, s0 - 1)
        if prev < 0 or not re.fullmatch(rb"[\x20-\x7e]+\.p3d", d[prev + 1:s0 - 1]):
            break
        s0 = prev + 1
    n = struct.unpack_from("<i", d, s0 - 4)[0]
    r = Reader(d)
    r.p = s0
    models = [r.asciiz() for _ in range(n)]
    if not all(x.lower().endswith(".p3d") for x in models):
        raise ValueError("model list not found where expected")
    for _ in range(r.i32()):                     # static entities: class, model, position, id (+1 int in v32)
        r.asciiz(); r.asciiz(); r.vec3(); r.i32()
        if version >= 32:
            r.i32()
    return d, version, record, models, r.p


def objects(path, land=None):
    """Yield (model path, matrix12, id, shape) for every placed object."""
    d, version, record, models, p = read_objects(path)
    r = Reader(d)
    r.p = p
    lx = land or guess_land(d)
    QuadTree(lx, lx, r, 4)
    size_objects = r.i32()
    QuadTree(lx, lx, r, 4)
    size_mapinfo = r.i32()
    start = len(d) - size_mapinfo - size_objects
    for k in range(size_objects // record):
        q = start + k * record
        oid, mi = struct.unpack_from("<2i", d, q)
        m = struct.unpack_from("<12f", d, q + 8)
        shape = struct.unpack_from("<i", d, q + 56)[0]
        yield models[mi], m, oid, shape


def guess_land(d):
    lx = struct.unpack_from("<i", d, 17 if struct.unpack_from("<i", d, 4)[0] >= 32 else 16)[0]
    return lx


def main():
    path = sys.argv[1]
    want = sys.argv[2].lower() if len(sys.argv) > 2 else None
    n = 0
    for model, m, oid, shape in objects(path):
        if want and want not in model.lower():
            continue
        yaw = math.degrees(math.atan2(m[6], m[8])) % 360
        print("%-60s pos %9.2f %8.2f %9.2f  yaw %6.1f  scale %.2f" % (model, m[9], m[10], m[11], yaw,
                                                                    math.sqrt(m[0] ** 2 + m[1] ** 2 + m[2] ** 2)))
        n += 1
        if n >= 40:
            break


if __name__ == "__main__":
    main()
