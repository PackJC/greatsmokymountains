"""Copy the server mission's Central Economy files into the map's ce folder, so they
pack inside greatsmokymountains.pbo as the world's own CE data.

    python tools/stage_ce.py mission/dayzOffline.greatsmokymountains ce

config.cpp points the world's ceFiles at greatsmokymountains\\ce, which is this
folder inside the PBO. Without it the world would inherit Chernarus's
(DZ\\worlds\\chernarusplus\\ce), so any CE file a server's mission folder lacks
would come from Chernarus. Everything in the mission except init.c and storage
folders is copied; the ce folder is replaced each time, so edit the mission, not
ce. tools/pack.py runs this before packing.
"""

import os
import shutil
import sys


def stage(mission, ce):
    mission, ce = os.path.abspath(mission), os.path.abspath(ce)
    if os.path.isdir(ce):
        shutil.rmtree(ce)
    count = 0
    for root, dirs, files in os.walk(mission):
        dirs[:] = [d for d in dirs if not d.lower().startswith("storage_")]
        rel = os.path.relpath(root, mission)
        for f in files:
            if rel == "." and f.lower() == "init.c":
                continue
            dst = os.path.normpath(os.path.join(ce, rel, f))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(root, f), dst)
            count += 1
    return count


def main():
    n = stage(sys.argv[1], sys.argv[2])
    print("%d mission files -> %s" % (n, os.path.abspath(sys.argv[2])))


if __name__ == "__main__":
    main()
