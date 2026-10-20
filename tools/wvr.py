"""Read and write DayZ's editable world format (8WVR), what Terrain Builder exports.

Layout (BIS.WRP EditableWrp): "8WVR", land range x/y, terrain range x/y, land
cell size, float heights (row 0 = south), uint16 material index per land cell,
material names (count, then each name as int32-length text followed by an
empty one), then objects (4x3 matrix: aside, up, dir, position; int32 id;
int32-length model path) ending with a dummy object (NaN matrix, id 2^31-1,
empty path).
"""

import math
import struct

import numpy as np

DUMMY_ID = 2 ** 31 - 1


def write_8wvr(path, land, terrain, land_cell, elevation, material_index, mat_names, objects):
    """objects: iterable of (model path, 12-float matrix, id)."""
    with open(path, "wb") as fh:
        fh.write(b"8WVR")
        fh.write(struct.pack("<4if", land[0], land[1], terrain[0], terrain[1], land_cell))
        fh.write(np.ascontiguousarray(elevation, "<f4").tobytes())
        fh.write(np.ascontiguousarray(material_index, "<u2").tobytes())
        fh.write(struct.pack("<i", len(mat_names)))
        for name in mat_names:
            if name:
                raw = name.encode("ascii")
                fh.write(struct.pack("<i", len(raw)) + raw)
            fh.write(struct.pack("<i", 0))
        count = 0
        for model, m, oid in objects:
            raw = model.encode("ascii")
            fh.write(struct.pack("<12fi", *m, oid) + struct.pack("<i", len(raw)) + raw)
            count += 1
        nan = float("nan")
        fh.write(struct.pack("<12fi", *([nan] * 12), DUMMY_ID) + struct.pack("<i", 0))
    return count


def read_8wvr(path, count_only=False):
    """The whole world; with count_only, objects are counted, not kept (for millions)."""
    d = open(path, "rb").read()
    if d[:4] != b"8WVR":
        raise ValueError("%s is not an editable world (8WVR)" % path)
    lx, ly, tx, ty, cell = struct.unpack_from("<4if", d, 4)
    p = 24
    elev = np.frombuffer(d, "<f4", tx * ty, p).reshape(ty, tx)
    p += 4 * tx * ty
    mats = np.frombuffer(d, "<u2", lx * ly, p).reshape(ly, lx)
    p += 2 * lx * ly
    n = struct.unpack_from("<i", d, p)[0]
    p += 4
    names = []
    for _ in range(n):
        name = ""
        while True:
            ln = struct.unpack_from("<i", d, p)[0]
            p += 4
            if ln == 0:
                break
            name = d[p:p + ln].decode("ascii")
            p += ln
        names.append(name)
    objects, count = [], 0
    while p < len(d):
        oid = struct.unpack_from("<i", d, p + 48)[0]
        ln = struct.unpack_from("<i", d, p + 52)[0]
        if ln == 0 and oid == DUMMY_ID:
            p += 56
            break
        if not count_only:
            vals = struct.unpack_from("<12f", d, p)
            objects.append((d[p + 56:p + 56 + ln].decode("ascii"), vals, oid))
        count += 1
        p += 56 + ln
    return {"land": (lx, ly), "terrain": (tx, ty), "land_cell": cell, "elevation": elev,
            "materials": mats, "mat_names": names, "objects": objects, "object_count": count,
            "trailing": len(d) - p}


def transform(x, height, z, yaw=0.0, pitch=0.0, roll=0.0, scale=1.0):
    """4x3 matrix rows (aside, up, dir, position) for a model at world (x, height, z),
    yaw clockwise from north in degrees, then pitch about its side axis and roll
    about its forward axis."""
    a, b, c = math.radians(yaw), math.radians(pitch), math.radians(roll)
    if b == 0.0 and c == 0.0:                    # upright: most objects, and fast
        ca, sa = math.cos(a) * scale, math.sin(a) * scale
        return [ca, 0.0, -sa, 0.0, scale, 0.0, sa, 0.0, ca, x, height, z]
    ry =np.array([[math.cos(a), 0, -math.sin(a)], [0, 1, 0], [math.sin(a), 0, math.cos(a)]])
    rx = np.array([[1, 0, 0], [0, math.cos(b), math.sin(b)], [0, -math.sin(b), math.cos(b)]])
    rz = np.array([[math.cos(c), math.sin(c), 0], [-math.sin(c), math.cos(c), 0], [0, 0, 1]])
    rot = rz @ rx @ ry * scale        # rows: aside, up, dir
    return [*rot[0], *rot[1], *rot[2], x, height, z]
