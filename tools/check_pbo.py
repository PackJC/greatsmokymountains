"""Check a built map PBO: what's inside, and the world's models and object count.

    python tools/check_pbo.py <mod folder>/Addons/greatsmokymountains.pbo

Fails if the world is missing, if anything from source/, tools/ or _build/ got
in, or if the world's object block isn't a whole number of object records.
Reads the parts of an OPRW v32 world that are stored uncompressed (current DayZ
Tools compresses the grids in a newer container this reader doesn't unpack):
the model list, entity infos and the size of the object block (64 bytes per
object in v32, 60 in v28).
"""

import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oprw import Reader, QuadTree  # noqa: E402


def read_pbo(path):
    d = open(path, "rb").read()
    pos, props, entries, first = 0, {}, [], True

    def asciiz():
        nonlocal pos
        end = d.index(b"\0", pos)
        s = d[pos:end].decode("latin-1")
        pos = end + 1
        return s

    while True:
        name = asciiz()
        packing, original, _, _, size = struct.unpack_from("<5I", d, pos)
        pos += 20
        if first and not name and packing == 0x56657273:
            while True:
                k = asciiz()
                if not k:
                    break
                props[k] = asciiz()
            first = False
            continue
        first = False
        if not name:
            break
        entries.append((name, packing, size))
    files, off = {}, pos
    for name, packing, size in entries:
        files[name.replace("/", "\\").lower()] = (off, size, packing)
        off += size
    return d, props, files


def world_summary(w):
    key = b"\\structures\\"
    version = struct.unpack_from("<i", w, 4)[0]
    record = 64 if version >= 32 else 60
    s0 = w.find(b"dz" + key)
    if s0 < 0:
        return version, [], 0, 0, record, {}
    for back in range(4, 1 << 16):
        n = struct.unpack_from("<i", w, s0 - back)[0]
        if 0 < n < 100000 and w[s0 - back + 4:s0 - back + 6].lower() in (b"dz", b"gr"):
            break
    r = Reader(w)
    r.p = s0 - back + 4
    models = [r.asciiz() for _ in range(n)]
    entities = {}
    for _ in range(r.i32()):                     # static entities (one more int in v32)
        cls = r.asciiz()
        r.asciiz(); r.vec3(); r.i32()
        if version >= 32:
            r.i32()
        entities[cls] = entities.get(cls, 0) + 1
    QuadTree(512, 512, r, 4)
    size_objects = r.i32()
    return version, models, size_objects, size_objects / record, record, entities


def main():
    d, props, files = read_pbo(sys.argv[1])
    print("PBO %s  %.1f MB  prefix %s  %d files" % (os.path.basename(sys.argv[1]), len(d) / 1e6,
                                                     props.get("prefix"), len(files)))
    tops = collections.Counter(n.split("\\")[0] if "\\" in n else n for n in files)
    print("top level:", dict(tops))
    bad = [n for n in files if n.split("\\")[0] in ("source", "tools", "_build", "mission", "map")]
    if bad:
        sys.exit("working files got into the PBO, e.g. %s" % bad[:5])
    ce = [n for n in files if n.lower().startswith("ce\\")]
    if not any(n.lower() == "ce\\cfgeconomycore.xml" for n in ce):
        sys.exit("the world's CE data (ce\\cfgeconomycore.xml) is missing from the PBO")
    print("CE data: %d files in ce\\" % len(ce))
    print("navmesh: %s" % ("navmesh\\navmesh.nm, %.0f MB" % (files["navmesh\\navmesh.nm"][1] / 1e6)
                           if "navmesh\\navmesh.nm" in files else "none packed (the AI stands still without it)"))
    if "greatsmokymountains.wrp" not in files:
        sys.exit("the world (greatsmokymountains.wrp) is missing from the PBO")
    off, size, packing = files["greatsmokymountains.wrp"]
    version, models, size_objects, count, record, entities = world_summary(d[off:off + size])
    print("world: OPRW v%d, %.1f MB, %d models" % (version, size / 1e6, len(models)))
    print("static entities (classed buildings: doors, loot): %d of %d classes; most: %s"
          % (sum(entities.values()), len(entities),
             ", ".join("%s %d" % kv for kv in sorted(entities.items(), key=lambda kv: -kv[1])[:6])))
    print("objects: %d bytes = %s objects of %d bytes" % (size_objects, ("%d" % count) if count == int(count) else "%.2f" % count, record))
    if count != int(count):
        sys.exit("object block is not a whole number of records")
    groups = collections.Counter(os.path.dirname(m) for m in models)
    for g, k in sorted(groups.items()):
        print("  %-40s %3d models" % (g, k))


if __name__ == "__main__":
    main()
