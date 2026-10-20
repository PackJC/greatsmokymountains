"""Measure where each bridge model's deck sits, from how the vanilla maps place them.

    python tools/bridge_decks.py <out.json> <world.wrp> ...

For every bridge in a vanilla world, the road parts touching its ends (within
reach of an end, along its axis) give the road height there. The deck height
above the bridge's position is the road height minus the bridge's own height.
Writes the median per model, with how many joins it came from.
"""

import json
import math
import os
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oprw_objects import objects  # noqa: E402
from odol_info import odol_info  # noqa: E402


def main():
    out, worlds = sys.argv[1], sys.argv[2:]
    result = {}
    for world in worlds:
        bridges, roads = [], []
        for model, m, oid, shape in objects(world):
            ml = model.lower()
            if "\\roads\\bridges\\" in ml:
                bridges.append((ml, m))
            elif "\\roads\\parts\\" in ml:
                roads.append((m[9], m[10], m[11]))
        if not roads:
            continue
        ra = np.array(roads)
        for ml, m in bridges:
            info = odol_info(os.path.join("P:\\", ml))
            half_x = (info["max"][0] - info["min"][0]) / 2
            half_z = (info["max"][2] - info["min"][2]) / 2
            # The span runs along the model's longer horizontal axis.
            if half_x > half_z:
                axis, half = np.array([m[0], m[1], m[2]]), half_x
            else:
                axis, half = np.array([m[6], m[7], m[8]]), half_z
            axis = axis / (np.linalg.norm(axis) or 1)
            c = np.array([m[9], m[10], m[11]])
            for sign in (-1, 1):
                end = c + axis * sign * half
                d = np.hypot(ra[:, 0] - end[0], ra[:, 2] - end[2])
                k = int(d.argmin())
                if d[k] < 15:
                    result.setdefault(os.path.basename(ml)[:-4], []).append(float(ra[k, 1] - c[1]))
        print("%s: %d bridges, %d road parts" % (os.path.basename(world), len(bridges), len(roads)))
    summary = {k: {"deck": round(statistics.median(v), 2), "joins": len(v),
                   "spread": round(statistics.pstdev(v), 2) if len(v) > 1 else None} for k, v in sorted(result.items())}
    json.dump(summary, open(out, "w"), indent=1)
    for k, v in summary.items():
        print("  %-28s deck %+6.2f m above its position  (%d joins, spread %s)" % (k, v["deck"], v["joins"], v["spread"]))


if __name__ == "__main__":
    main()
