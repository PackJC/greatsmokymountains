"""Check that road parts meet: rebuild each part's two ends from the Terrain Builder
rows, as the game will place them, and measure how far each end is from the
nearest end of another part.

    python tools/check_roads.py <ground .npy> source/roads/tb_roads_main.txt source/roads/tb_roads_local.txt

A part's start is its model's origin, heading +z; straights end at (0, 0, L), arcs
"N R" at (R(1-cos N), 0, R sin N) (tools/road_build.py). Joints are exact when an
end meets another within a few millimetres; ends meeting nothing are road ends
(junctions, dead ends, bridges), and joints under a short part laid across a
sharp corner are covered, not exact.
"""

import math
import os
import re
import sys

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import bilinear  # noqa: E402
from odol_info import odol_info  # noqa: E402

PARTS = r"P:\DZ\structures\roads\parts"
ANG = {"7": 7.5, "22": 22.5, "0": 0.5}


def shape_ends(name):
    m = re.match(r"^[a-z0-9]+_(\d+) (\d+)$", name)
    if m:
        a = math.radians(ANG.get(m.group(1), float(m.group(1))))
        R = float(m.group(2))
        return np.array([R * (1 - math.cos(a)), 0.0, R * math.sin(a)])
    m = re.match(r"^[a-z0-9]+_(25|12|6|6konec)$", name)
    L = {"25": 25.0, "12": 12.5, "6": 6.25, "6konec": 6.25}[m.group(1)]
    return np.array([0.0, 0.0, L])


def main():
    ground = np.load(sys.argv[1])
    cell = 20480.0 / ground.shape[0]
    cen = {}
    ends, names = [], []
    for f in sys.argv[2:]:
        for line in open(f):
            p = line.strip().rstrip(";").split(";")
            name = p[0].strip('"')
            x, z, yaw, pitch, roll, scale, rel = (float(v) for v in p[1:8])
            x -= 200000.0
            if name not in cen:
                cen[name] = np.array(odol_info(os.path.join(PARTS, name + ".p3d"))["center"])
            a, b = math.radians(yaw), math.radians(pitch)
            ca, sa = math.cos(a), math.sin(a)
            aside = np.array([ca, 0.0, -sa])
            dirv = np.array([math.cos(b) * sa, -math.sin(b), math.cos(b) * ca])
            up = np.array([math.sin(b) * sa, math.cos(b), math.sin(b) * ca])
            pos = np.array([x, bilinear(ground, x / cell, z / cell) + rel, z])
            C = cen[name]

            def world(q):
                q = q - C
                return pos + aside * q[0] + up * q[1] + dirv * q[2]
            ends.append(world(np.zeros(3)))
            ends.append(world(shape_ends(name)))
            names.append(name)
    E = np.array(ends)
    t = cKDTree(E[:, [0, 2]])
    d, k = t.query(E[:, [0, 2]], k=2)
    nd, nk = d[:, 1], k[:, 1]
    dy = np.abs(E[:, 1] - E[nk, 1])
    exact = nd < 0.01
    print("%d parts, %d ends" % (len(names), len(E)))
    print("  ends meeting another end within 1 cm: %.1f%% (height step there: median %.3f m, max %.3f m)"
          % (100 * exact.mean(), np.median(dy[exact]) if exact.any() else 0, dy[exact].max() if exact.any() else 0))
    steps = exact & (dy > 0.05)
    print("  of those, with a height step over 5 cm: %d" % steps.sum())
    for i in np.where(steps)[0][:8]:
        print("     at %.1f %.1f: step %.2f m (%s / %s)" % (E[i, 0], E[i, 2], dy[i], names[i // 2], names[nk[i] // 2]))
    for lo, hi in ((0.01, 0.1), (0.1, 0.5), (0.5, 2.0), (2.0, 1e9)):
        sel = (nd >= lo) & (nd < hi)
        print("  nearest other end %5.2f-%-5s m: %6d ends" % (lo, ("%.1f" % hi) if hi < 1e8 else "more", sel.sum()))


if __name__ == "__main__":
    main()
