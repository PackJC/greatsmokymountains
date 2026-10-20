"""Write an ESRI polyline shapefile (.shp, .shx, .dbf) with no outside libraries."""

import datetime
import struct

POLYLINE = 3


def _header(file_words, bbox):
    return (struct.pack(">7i", 9994, 0, 0, 0, 0, 0, file_words)
            + struct.pack("<2i", 1000, POLYLINE)
            + struct.pack("<8d", bbox[0], bbox[1], bbox[2], bbox[3], 0, 0, 0, 0))


def write_polylines(base, lines, fields, records):
    """lines: list of [(x, y), ...]; fields: [(name, 'C'|'N', length, decimals)];
    records: one tuple of field values per line."""
    xs = [p[0] for line in lines for p in line]
    ys = [p[1] for line in lines for p in line]
    bbox = (min(xs), min(ys), max(xs), max(ys))

    contents = []
    for line in lines:
        lx, ly = [p[0] for p in line], [p[1] for p in line]
        body = struct.pack("<i4d2i", POLYLINE, min(lx), min(ly), max(lx), max(ly), 1, len(line))
        body += struct.pack("<i", 0)
        body += b"".join(struct.pack("<2d", x, y) for x, y in line)
        contents.append(body)

    shp_words = 50 + sum(4 + len(c) // 2 for c in contents)
    with open(base + ".shp", "wb") as shp, open(base + ".shx", "wb") as shx:
        shp.write(_header(shp_words, bbox))
        shx.write(_header(50 + 4 * len(contents), bbox))
        offset = 50
        for i, c in enumerate(contents, 1):
            shp.write(struct.pack(">2i", i, len(c) // 2) + c)
            shx.write(struct.pack(">2i", offset, len(c) // 2))
            offset += 4 + len(c) // 2

    rec_len = 1 + sum(f[2] for f in fields)
    today = datetime.date.today()
    with open(base + ".dbf", "wb") as dbf:
        dbf.write(struct.pack("<4BIHH20x", 3, today.year - 1900, today.month, today.day,
                              len(records), 32 + 32 * len(fields) + 1, rec_len))
        for name, typ, length, dec in fields:
            dbf.write(struct.pack("<11sc4xBB14x", name.encode("ascii"), typ.encode("ascii"), length, dec))
        dbf.write(b"\r")
        for rec in records:
            dbf.write(b" ")
            for (name, typ, length, dec), value in zip(fields, rec):
                if typ == "N":
                    text = ("%.*f" % (dec, value)) if dec else ("%d" % value)
                    dbf.write(text.rjust(length)[:length].encode("ascii"))
                else:
                    dbf.write(str(value).encode("latin-1", "replace")[:length].ljust(length))
        dbf.write(b"\x1a")

    with open(base + ".cpg", "w") as fh:
        fh.write("ISO-8859-1")
