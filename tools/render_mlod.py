"""Quick look at an MLOD model's visual LOD: flat-shaded, painter's algorithm.

    python tools/render_mlod.py <model.p3d> <out.png> [yaw pitch zoom target_z]

Faces are drawn back-to-front from an oblique camera, coloured by texture
(steel dark grey, planks brown, glass pale blue, mesh grey) and shaded by their
normal. Back faces are skipped, so a face wound the wrong way shows as a hole.
"""

import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlod  # noqa: E402

COLOURS = {"metal": (70, 72, 78), "planks": (140, 100, 60), "glass": (170, 210, 235), "fence": (150, 150, 150)}


def colour(tex):
    t = tex.lower()
    for k, c in COLOURS.items():
        if k in t:
            return np.array(c, float)
    return np.array((200, 200, 200), float)


def main():
    path, out = sys.argv[1], sys.argv[2]
    yaw, pitch, zoom, tz = (float(v) for v in (sys.argv[3:7] + ["35", "25", "4", "0"][len(sys.argv[3:7]):]))
    m = mlod.read(path)
    L = m["lods"][0]
    P = L["pts"]
    a, b = math.radians(yaw), math.radians(pitch)
    R = np.array([[math.cos(a), 0, -math.sin(a)], [0, 1, 0], [math.sin(a), 0, math.cos(a)]])
    T = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    M = T @ R
    Q = (P - np.array([0, 0, tz])) @ M.T
    W, H = 1600, 900
    light = np.array([0.4, 0.8, -0.45])
    light /= np.linalg.norm(light)
    polys = []
    for f in L["faces"]:
        idx = [f["v"][k][0] for k in range(f["n"])][::-1]            # back to counter-clockwise from outside
        c = P[idx]
        n = np.cross(c[1] - c[0], c[2] - c[0])
        if np.linalg.norm(n) < 1e-12:
            continue
        n /= np.linalg.norm(n)
        nv = n @ M.T
        if nv[2] > 0 and "fence" not in f["tex"].lower():               # facing away from the camera
            continue
        q = Q[idx]
        shade = 0.45 + 0.55 * max(0.0, float(n @ light))
        col = tuple(int(v) for v in np.clip(colour(f["tex"]) * shade, 0, 255))
        polys.append((q[:, 2].mean(), [(W / 2 + p[0] * zoom, H / 2 - p[1] * zoom) for p in q], col))
    img = Image.new("RGB", (W, H), (205, 220, 235))
    d = ImageDraw.Draw(img)
    for _, pts, col in sorted(polys, key=lambda t: -t[0]):
        d.polygon(pts, fill=col)
    img.save(out)
    print("%d faces drawn -> %s" % (len(polys), out))


if __name__ == "__main__":
    main()
