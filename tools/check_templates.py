"""Check every template the object lists use resolves to exactly one model.

    python tools/check_templates.py <models folder> ...

tools/build_world.py looks templates up by model file name across its --models
folders; a name found in two folders would quietly take the first.
"""

import collections
import glob
import os
import sys


def main():
    where = collections.defaultdict(list)
    for f in sys.argv[1:]:
        for p in glob.glob(os.path.join(f, "**", "*.p3d"), recursive=True):
            where[os.path.basename(p)[:-4].lower()].append(p)
    used = collections.Counter()
    for f in glob.glob(os.path.join("source", "*", "tb_*.txt")):
        for line in open(f):
            used[line.split(";", 1)[0].strip().strip('"').lower()] += 1
    missing = sorted(u for u in used if u not in where)
    dup = {u: where[u] for u in used if len(where.get(u, [])) > 1}
    print("templates used: %d, objects: %d" % (len(used), sum(used.values())))
    print("missing: %s" % (missing or "none"))
    print("in more than one folder: %s" % (dup or "none"))
    sys.exit(1 if missing or dup else 0)


if __name__ == "__main__":
    main()
