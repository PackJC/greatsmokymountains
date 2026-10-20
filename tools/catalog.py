"""List the footprint of every binarized model under some folders, as JSON.

    python tools/catalog.py <out.json> <folder> ...

One entry per model: game path, width (x), length (z) and height, plus the
bounding centre (where the model's own origin sits; see tools/odol_info.py).
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from odol_info import odol_info  # noqa: E402


def main():
    out, folders = sys.argv[1], sys.argv[2:]
    rows = []
    for folder in folders:
        for f in sorted(glob.glob(os.path.join(folder, "**", "*.p3d"), recursive=True)):
            i = odol_info(f)
            if not i:
                continue
            w = i["max"][0] - i["min"][0]
            h = i["max"][1] - i["min"][1]
            l = i["max"][2] - i["min"][2]
            rows.append({"path": os.path.relpath(f, "P:\\").lower(), "name": os.path.basename(f)[:-4].lower(),
                         "w": round(w, 2), "l": round(l, 2), "h": round(h, 2),
                         "center": [round(c, 3) for c in i["center"]]})
    json.dump(rows, open(out, "w"), indent=0)
    print("%d models -> %s" % (len(rows), out))


if __name__ == "__main__":
    main()
