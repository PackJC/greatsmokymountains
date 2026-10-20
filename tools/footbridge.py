"""Log footbridges, as on the Smokies' trails (Alum Cave, Porters Creek): one big log
hewn flat on top, a pole handrail on one side, for tools/details.py to lay over the
creeks where trails cross them.

    make_footbridge(length, model_dir) -> template name (gsm_footbridge_<length>)

The log runs along the model's z, from -length/2 to +length/2, its flat top 0.6 m
wide at y = 0 (the origin, autocenter 0, is the middle of the walking surface),
0.65 m deep; the rail is on the +x side, 1 m high, on posts every 2 m or so. LODs as
the SkyBridge's (tools/skybridge.py): visual, Geometry with mass (the log in
convex pieces, the rail), View and Fire Geometry (wood), and Roadway (the flat
top, so you walk on it).
"""

import math
import os

import numpy as np

import mlod
from skybridge import Lod, PEN, ROADWAY, box, prop

BARK = r"dz\structures\data\wood\wood_bark_old_co.paa"
HEWN = r"dz\structures\data\wood\wood_barkstripped_co.paa"
END = r"dz\structures\data\wood\wood_end_co.paa"
RAIL = r"dz\structures\data\wood\wood_plank_old_co.paa"
# The log's cross-section (x, y), counter-clockwise seen from +z: a flat top 0.6 m wide.
SECTION = [(-0.30, 0.0), (0.30, 0.0), (0.42, -0.12), (0.46, -0.32), (0.38, -0.52), (0.20, -0.64),
           (-0.20, -0.64), (-0.38, -0.52), (-0.46, -0.32), (-0.42, -0.12)]
PIECE = 4.0                      # the log's geometry in convex pieces about this long
RAIL_X, RAIL_H, POST_EVERY = 0.38, 1.0, 2.0


def model(length):
    vis, geom, view, fire, road = Lod(1.0), Lod(1e13), Lod(6e15), Lod(7e15), Lod(3e15)
    h = length / 2
    ring = [np.array(p) for p in SECTION]
    n = len(ring)
    # The log: bark round the sides, hewn wood on top, cut ends.
    for k in range(n):
        a, b = ring[k], ring[(k + 1) % n]
        quad = [(a[0], a[1], -h), (a[0], a[1], h), (b[0], b[1], h), (b[0], b[1], -h)]
        out = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.32, 0.0)
        w = float(np.hypot(*(b - a)))
        tex = HEWN if k == 0 else BARK
        vis.face(quad, [(0, 0), (0, length / 2), (w * 2, length / 2), (w * 2, 0)], tex, out=out)
    for z, s in ((h, 1), (-h, -1)):
        corners = [(p[0], p[1], z) for p in ring]
        vis.face(corners[:4], [(0.5 + p[0], 0.5 - p[1]) for p in ring[:4]], END, out=(0, 0, s))
        for k in range(3, n - 1, 2):                    # the rest of the end as a fan of quads
            q = [corners[0], corners[k], corners[k + 1], corners[(k + 2) % n]]
            vis.face(q, [(0.5 + p[0], 0.5 - p[1]) for p in (ring[0], ring[k], ring[k + 1], ring[(k + 2) % n])],
                     END, out=(0, 0, s))
    # The walking surface.
    road.face([(-0.30, 0.0, -h), (-0.30, 0.0, h), (0.30, 0.0, h), (0.30, 0.0, -h)],
              [(0, 0), (0, 1), (1, 1), (1, 0)], ROADWAY, out=(0, 1, 0))
    comp = [0]

    def component(corners8, mass):
        comp[0] += 1
        sel = "Component%02d" % comp[0]
        geom.solid(corners8, sel=sel, mass=mass)
        view.solid(corners8, sel=sel)
        fire.solid(corners8, mat=PEN["wood"], sel=sel)
    pieces = max(1, int(math.ceil(length / PIECE)))
    for k in range(pieces):
        z0, z1 = -h + length * k / pieces, -h + length * (k + 1) / pieces
        component([(-0.42, -0.62, z0), (0.42, -0.62, z0), (0.42, -0.62, z1), (-0.42, -0.62, z1),
                   (-0.30, 0.0, z0), (0.30, 0.0, z0), (0.30, 0.0, z1), (-0.30, 0.0, z1)], 120.0 * (z1 - z0))
    # The handrail: posts set into the log's side, a pole along their tops.
    posts = max(2, int(round(length / POST_EVERY)) + 1)
    for z in np.linspace(-h + 0.3, h - 0.3, posts):
        p = box(RAIL_X, (RAIL_H - 0.3) / 2, z, 0.04, (RAIL_H + 0.3) / 2, 0.04)
        vis.solid(p, RAIL, uv_scale=1.0)
    rail = box(RAIL_X, RAIL_H, 0.0, 0.04, 0.04, h - 0.25)
    vis.solid(rail, RAIL, uv_scale=1.0)
    component(box(RAIL_X, RAIL_H / 2, 0.0, 0.05, RAIL_H / 2 + 0.05, h - 0.25), 30.0)
    geom.props = [prop("autocenter", "0")]
    return dict(version=257, lods=[vis.to_mlod(), geom.to_mlod(), view.to_mlod(), fire.to_mlod(), road.to_mlod()])


def make_footbridge(length, model_dir):
    os.makedirs(model_dir, exist_ok=True)
    name = "gsm_footbridge_%02d" % int(round(length))
    path = os.path.join(model_dir, name + ".p3d")
    mlod.write(model(float(length)), path)
    assert len(mlod.read(path)["lods"]) == 5
    return name
