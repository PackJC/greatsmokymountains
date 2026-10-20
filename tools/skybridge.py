"""Model the Gatlinburg SkyBridge and place it where OpenStreetMap has it.

    python tools/skybridge.py source/buildings/elevation.npy tools/georef.json source/roads/osm_highways.json
        data/skybridge source/buildings

The real bridge: a 680 ft (207 m) pedestrian suspension bridge at SkyLift Park
on Crockett Mountain, with a glass-floored section at mid-span. The model is
built for this exact span (OSM way "Gatlinburg SkyBridge"): its deck meets the
ground at both real end points and sags between them.

Writes <model dir>/skybridge.p3d (MLOD, packed and binarized with the map) and
<out>/tb_skybridge.txt (its placement), and drops trees, bushes, deadwood and
rocks from the corridor under it in the other object lists.

LODs, in the conventions of gebsfish's models (tools/mlod.py): a visual LOD
(steel portal towers and backstays, timber deck, posts, handrails, wire-mesh
railing panels, two parabolic main cables with hangers, glass deck panels),
Geometry (convex boxes: deck, both railings, tower legs and beams, with mass;
autocenter 0 so the model's origin is where it's placed), View and Fire
Geometry (the same boxes, with wood, iron and glass penetration materials) and
Roadway (the deck's walking surface, timber planks).
"""

import json
import math
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlod  # noqa: E402
from geo import utm  # noqa: E402

EASTING = 200000.0
WAY_NAME = "Gatlinburg SkyBridge"
WIDTH = 1.8                      # walkway
DECK_T = 0.25                    # deck thickness
STEP = 3.0                       # station spacing along the span
SAG = 3.0                        # deck sag at mid-span below the straight line between the ends
TOWER_H = 10.0                   # tower top above the deck end
RAIL_H = 1.2
GLASS = 4.5                      # glass floor from -GLASS to +GLASS along the span (three panels)
CORRIDOR = 7.0                   # clear this far either side of the span
END_LIFT = 1.0                   # deck ends this far over the highest ground near them (their landings)
END_LOOK = 25.0                  # ...looking this far in from each end
MIN_CLEAR = 1.5                  # the deck clears the ground by at least this everywhere between the ends
RAMP = 6.0                       # a planked ramp from each deck end down to the ground beyond it

STEEL = r"dz\structures\data\metal\metal_servicehangar_black_co.paa"
PLANKS = r"dz\structures\data\wood\bridge_wood_planks_co.paa"
MESH = r"dz\structures\data\metal\metal_fence_wire_ca.paa"
GLASS_TEX = r"dz\structures\residential\stores\data\generalstore_glass_ca.paa"
GLASS_MAT = r"dz\structures\residential\stores\data\generalstore_glass.rvmat"
ROADWAY = r"dz\surfaces\data\roadway\wood_planks_ext.paa"
PEN = {"wood": r"dz\data\data\penetration\wood.rvmat", "iron": r"dz\data\data\penetration\iron.rvmat",
       "glass": r"dz\data\data\penetration\glass.rvmat"}


class Lod:
    """Faces with their own corners (flat shading). Corners are given counter-clockwise
    seen from outside; written reversed with inward normals (Arma's MLOD convention)."""

    def __init__(self, res):
        self.res = res
        self.pts, self.norms, self.faces = [], [], []
        self.uvs = bytearray(struct.pack("<I", 0))
        self.sel_pts, self.sel_faces = {}, {}
        self.mass = []
        self.props = []

    def face(self, corners, uvs, tex="", mat="", sel=None, mass_each=None, out=None):
        """out: a direction the face should look along (corners are flipped to match);
        None keeps the order given (for two-sided panels, give both orders)."""
        c = [np.asarray(p, float) for p in corners]
        n = np.cross(c[1] - c[0], c[2] - c[0])
        if len(c) == 4:
            n = n + np.cross(c[2] - c[0], c[3] - c[0])
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            return
        n = n / ln
        if out is not None and float(n @ np.asarray(out, float)) < 0:
            c, uvs, n = c[::-1], list(uvs)[::-1], -n
        base = len(self.pts)
        ni = len(self.norms)
        self.norms.append(-n)
        for p in c:
            self.pts.append(p)
            self.mass.append(mass_each or 0.0)
        vs = []
        for k in reversed(range(len(c))):
            u, v = uvs[k]
            vs.append((base + k, ni, float(u), float(v)))
            self.uvs += struct.pack("<ff", u, v)
        while len(vs) < 4:
            vs.append((0, 0, 0.0, 0.0))
        fi = len(self.faces)
        self.faces.append(dict(n=len(c), v=vs, flags=0, tex=tex, mat=mat))
        if sel:
            self.sel_pts.setdefault(sel, set()).update(range(base, base + len(c)))
            self.sel_faces.setdefault(sel, set()).add(fi)

    def solid(self, corners8, tex="", mat="", sel=None, mass=None, uv_scale=2.0):
        """A convex hexahedron: corners8 = bottom (0..3) then top (4..7), each ring
        counter-clockwise seen from above. Welded corners (8 points) when sel is given,
        as geometry components need."""
        b = [np.asarray(p, float) for p in corners8]
        centre = np.mean(b, axis=0)
        quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        if sel:                                      # geometry-style: shared points, one component
            base = len(self.pts)
            for p in b:
                self.pts.append(p)
                self.mass.append((mass or 0.0) / 8.0)
            fis = []
            for q in quads:
                c = [b[i] for i in q]
                n = np.cross(c[1] - c[0], c[2] - c[0]) + np.cross(c[2] - c[0], c[3] - c[0])
                n = n / (np.linalg.norm(n) or 1)
                if float(n @ (np.mean(c, axis=0) - centre)) < 0:     # face away from the centre
                    q, n = q[::-1], -n
                ni = len(self.norms)
                self.norms.append(-n)
                vs = [(base + i, ni, 0.0, 0.0) for i in reversed(q)]
                for _ in q:
                    self.uvs += struct.pack("<ff", 0.0, 0.0)
                fis.append(len(self.faces))
                self.faces.append(dict(n=4, v=vs, flags=0, tex=tex, mat=mat))
            self.sel_pts.setdefault(sel, set()).update(range(base, base + 8))
            self.sel_faces.setdefault(sel, set()).update(fis)
            return
        for q in quads:
            c = [b[i] for i in q]
            e1 = np.linalg.norm(c[1] - c[0]) / uv_scale
            e2 = np.linalg.norm(c[3] - c[0]) / uv_scale
            self.face(c, [(0, 0), (e1, 0), (e1, e2), (0, e2)], tex, mat, out=np.mean(c, axis=0) - centre)

    def to_mlod(self):
        npts, nf = len(self.pts), len(self.faces)
        taggs = [(1, "#UVSet#", bytes(self.uvs))]
        if any(self.mass) and self.res == 1e13:
            taggs.append((1, "#Mass#", struct.pack("<%df" % npts, *self.mass)))
        taggs += self.props
        for nm in sorted(set(self.sel_pts) | set(self.sel_faces)):
            sp, sf = self.sel_pts.get(nm, set()), self.sel_faces.get(nm, set())
            taggs.append((1, nm, bytes(1 if i in sp else 0 for i in range(npts))
                          + bytes(1 if i in sf else 0 for i in range(nf))))
        taggs.append((1, "#EndOfFile#", b""))
        return dict(res=self.res, major=28, minor=256, flags=0, pts=np.asarray(self.pts, float).reshape(-1, 3),
                    pflags=np.zeros(npts, np.uint32), norms=np.asarray(self.norms, float).reshape(-1, 3),
                    faces=self.faces, taggs=taggs)


def prop(name, value):
    return (1, "#Property#", name.encode().ljust(64, b"\0") + value.encode().ljust(64, b"\0"))


def box(cx, cy, cz, hx, hy, hz):
    """Axis-aligned box corners: bottom ring then top ring, counter-clockwise from above."""
    return [(cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz + hz),
            (cx - hx, cy - hy, cz + hz), (cx - hx, cy + hy, cz - hz), (cx + hx, cy + hy, cz - hz),
            (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz)]


def slab(z0, y0, z1, y1, x0, x1, below, above):
    """Hexahedron between two stations: x0..x1 across, from below to above the line y(z)."""
    return [(x0, y0 - below, z0), (x1, y0 - below, z0), (x1, y1 - below, z1), (x0, y1 - below, z1),
            (x0, y0 + above, z0), (x1, y0 + above, z0), (x1, y1 + above, z1), (x0, y1 + above, z1)]


def tube(p0, p1, r):
    """Square tube between two points (for cables, hangers, backstays): 4 side faces,
    each as (corners, outward direction)."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    d = p1 - p0
    d /= np.linalg.norm(d)
    a = np.cross(d, [0, 1, 0]) if abs(d[1]) < 0.9 else np.cross(d, [1, 0, 0])
    a /= np.linalg.norm(a)
    b = np.cross(d, a)
    ring = [a * r + b * r, -a * r + b * r, -a * r - b * r, a * r - b * r]
    return [([p0 + ring[k], p0 + ring[(k + 1) % 4], p1 + ring[(k + 1) % 4], p1 + ring[k]],
             ring[k] + ring[(k + 1) % 4]) for k in range(4)]


def sample(grid, x, z):
    fx, fz = x / 5.0, z / 5.0
    x0 = min(max(int(fx), 0), grid.shape[1] - 2)
    z0 = min(max(int(fz), 0), grid.shape[0] - 2)
    tx, tz = fx - x0, fz - z0
    return float(grid[z0, x0] * (1 - tx) * (1 - tz) + grid[z0, x0 + 1] * tx * (1 - tz)
                 + grid[z0 + 1, x0] * (1 - tx) * tz + grid[z0 + 1, x0 + 1] * tx * tz)


def main():
    elev_path, georef_path, osm_path, model_dir, out = sys.argv[1:6]
    os.makedirs(model_dir, exist_ok=True)
    elev = np.load(elev_path).astype(np.float64)
    geo = json.load(open(georef_path))
    ox, oy = geo["offset_x"], geo["offset_y"]
    way = next(e for e in json.load(open(osm_path, encoding="utf-8"))["elements"]
               if e["type"] == "way" and e.get("tags", {}).get("name") == WAY_NAME)
    pts = [utm(p["lat"], p["lon"], 17) for p in way["geometry"]]
    a = np.array([pts[0][0] + ox, pts[0][1] + oy])
    b = np.array([pts[-1][0] + ox, pts[-1][1] + oy])
    span = float(np.hypot(*(b - a)))
    u = (b - a) / span
    mid = (a + b) / 2
    half = span / 2

    def ground(z):
        return sample(elev, *(mid + u * z))
    # The ends land on the highest ground near them (plus END_LIFT), then the whole deck
    # rises until it clears the ground everywhere between them.
    look = np.linspace(0, END_LOOK, 26)
    ha = max(ground(-half + d) for d in look) + END_LIFT
    hb = max(ground(half - d) for d in look) + END_LIFT
    inner = np.linspace(-half + 1, half - 1, 400)
    for _ in range(20):
        lowest = min(((ha + hb) / 2 + (hb - ha) * (z / span) - SAG * (1 - (2 * z / span) ** 2)) - ground(z)
                     for z in inner)
        if lowest >= MIN_CLEAR:
            break
        ha += MIN_CLEAR - lowest
        hb += MIN_CLEAR - lowest
    hm = (ha + hb) / 2

    def deck_y(z):                                  # local deck height (origin at hm)
        t = (z + half) / span
        return (ha - hm) + (hb - ha) * t - SAG * 4 * t * (1 - t)

    def cable_y(z):
        return deck_y(z) + RAIL_H + 0.1 + (TOWER_H - RAIL_H - 0.1) * (2 * z / span) ** 2

    # valley under the span, for the record
    clear = min(deck_y(z) + hm - ground(z) for z in inner)
    deepest = max(deck_y(z) + hm - ground(z) for z in inner)

    vis, geom, fire, road = Lod(1.0), Lod(1e13), Lod(7e15), Lod(3e15)
    view = Lod(6e15)
    comp = [0]

    def component(corners8, pen, mass):
        comp[0] += 1
        sel = "Component%02d" % comp[0] if comp[0] < 100 else "Component%d" % comp[0]
        geom.solid(corners8, sel=sel, mass=mass)
        view.solid(corners8, sel=sel)
        fire.solid(corners8, mat=PEN[pen], sel=sel)

    w = WIDTH / 2
    n = int(math.ceil(span / STEP))
    zs = np.linspace(-half, half, n + 1)
    for z0, z1 in zip(zs[:-1], zs[1:]):
        y0, y1 = deck_y(z0), deck_y(z1)
        glass = abs((z0 + z1) / 2) < GLASS
        # deck: planks (or glass) on top and below, steel edges
        top = [(-w, y0, z0), (w, y0, z0), (w, y1, z1), (-w, y1, z1)]
        bot = [(-w, y0 - DECK_T, z0), (-w, y1 - DECK_T, z1), (w, y1 - DECK_T, z1), (w, y0 - DECK_T, z0)]
        ln = z1 - z0
        up, down = (0, 1, 0), (0, -1, 0)
        if glass:
            vis.face(top, [(0, 0), (1, 0), (1, 1), (0, 1)], GLASS_TEX, GLASS_MAT, out=up)
            vis.face(bot, [(0, 0), (0, 1), (1, 1), (1, 0)], GLASS_TEX, GLASS_MAT, out=down)
        else:
            vis.face(top, [(0, 0), (1, 0), (1, ln / 2), (0, ln / 2)], PLANKS, out=up)
            vis.face(bot, [(0, 0), (0, ln / 2), (1, ln / 2), (1, 0)], PLANKS, out=down)
        for x in (-w, w):
            side = [(x, y0 - DECK_T, z0), (x, y1 - DECK_T, z1), (x, y1, z1), (x, y0, z0)]
            vis.face(side, [(0, 0), (ln / 2, 0), (ln / 2, 0.12), (0, 0.12)], STEEL, out=(x, 0, 0))
        road.face(top, [(0, 0), (1, 0), (1, 1), (0, 1)], ROADWAY, out=up)
        component(slab(z0, y0, z1, y1, -w, w, DECK_T, 0.0), "glass" if glass else "wood", 400.0)
        # railings: handrail tube, mesh panel (both faces), collision wall
        for s in (-1, 1):
            x = s * (w - 0.04)
            for f, o in tube((x, y0 + RAIL_H, z0), (x, y1 + RAIL_H, z1), 0.035):
                vis.face(f, [(0, 0), (0.1, 0), (0.1, ln / 2), (0, ln / 2)], STEEL, out=o)
            panel = [(x, y0 + 0.08, z0), (x, y1 + 0.08, z1), (x, y1 + RAIL_H - 0.04, z1), (x, y0 + RAIL_H - 0.04, z0)]
            for quad in (panel, panel[::-1]):
                vis.face(quad, [(0, 0), (ln, 0), (ln, 1.2), (0, 1.2)], MESH)
            component(slab(z0, y0, z1, y1, x - 0.05, x + 0.05, 0.0, RAIL_H), "iron", 30.0)
            # main cable and hanger
            cx = s * (w + 0.12)
            for f, o in tube((cx, cable_y(z0), z0), (cx, cable_y(z1), z1), 0.06):
                vis.face(f, [(0, 0), (0.2, 0), (0.2, ln), (0, ln)], STEEL, out=o)
            if cable_y(z0) - y0 > RAIL_H + 0.3:
                for f, o in tube((cx, y0, z0), (cx, cable_y(z0), z0), 0.02):
                    vis.face(f, [(0, 0), (0.1, 0), (0.1, 1), (0, 1)], STEEL, out=o)
        # railing post at each station
        for s in (-1, 1):
            vis.solid(box(s * (w - 0.04), y0 + RAIL_H / 2, z0, 0.04, RAIL_H / 2, 0.04), STEEL)

    # ramps: from each deck end down to the ground beyond it
    for end in (-1, 1):
        z0, z1 = end * half, end * (half + RAMP)
        y0, y1 = deck_y(z0), ground(z1) - hm + 0.05
        if end < 0:
            z0, z1, y0, y1 = z1, z0, y1, y0
        top = [(-w, y0, z0), (w, y0, z0), (w, y1, z1), (-w, y1, z1)]
        bot = [(-w, y0 - DECK_T, z0), (-w, y1 - DECK_T, z1), (w, y1 - DECK_T, z1), (w, y0 - DECK_T, z0)]
        vis.face(top, [(0, 0), (1, 0), (1, RAMP / 2), (0, RAMP / 2)], PLANKS, out=(0, 1, 0))
        vis.face(bot, [(0, 0), (0, RAMP / 2), (1, RAMP / 2), (1, 0)], PLANKS, out=(0, -1, 0))
        for x in (-w, w):
            side = [(x, y0 - DECK_T, z0), (x, y1 - DECK_T, z1), (x, y1, z1), (x, y0, z0)]
            vis.face(side, [(0, 0), (RAMP / 2, 0), (RAMP / 2, 0.12), (0, 0.12)], STEEL, out=(x, 0, 0))
        road.face(top, [(0, 0), (1, 0), (1, 1), (0, 1)], ROADWAY, out=(0, 1, 0))
        component(slab(z0, y0, z1, y1, -w, w, DECK_T, 0.0), "wood", 300.0)

    # towers: a steel portal at each end, legs into the ground, backstays to anchors behind
    for end in (-1, 1):
        z = end * (half - 1.0)
        ye = deck_y(end * half)
        lx = w + 0.6
        for s in (-1, 1):
            leg = box(s * lx, ye + (TOWER_H + 0.5 - 6.0) / 2, z, 0.25, (TOWER_H + 0.5 + 6.0) / 2, 0.25)
            vis.solid(leg, STEEL)
            component(leg, "iron", 3000.0)
            top = np.array([s * (w + 0.12), ye + TOWER_H, z])
            anchor = np.array([s * (w + 1.5), ye - 1.5, end * (half + 9.0)])
            for f, o in tube(top, anchor, 0.06):
                vis.face(f, [(0, 0), (0.2, 0), (0.2, 4), (0, 4)], STEEL, out=o)
            vis.solid(box(anchor[0], anchor[1], anchor[2], 0.6, 0.6, 0.6), STEEL)
        for yb in (ye + TOWER_H + 0.2, ye + 3.0):
            beam = box(0.0, yb, z, lx + 0.25, 0.25, 0.25)
            vis.solid(beam, STEEL)
            component(beam, "iron", 1500.0)
        # main cables from the last station up to the tower tops
        for s in (-1, 1):
            cx = s * (w + 0.12)
            for f, o in tube((cx, cable_y(end * half), end * half), (cx, ye + TOWER_H, z), 0.06):
                vis.face(f, [(0, 0), (0.2, 0), (0.2, 1), (0, 1)], STEEL, out=o)

    geom.props = [prop("autocenter", "0")]
    lods = [vis.to_mlod(), geom.to_mlod(), view.to_mlod(), fire.to_mlod(), road.to_mlod()]
    path = os.path.join(model_dir, "skybridge.p3d")
    mlod.write(dict(version=257, lods=lods), path)
    back = mlod.read(path)
    assert len(back["lods"]) == 5

    # placement: origin at the span's midpoint, at the mean of the end heights; +z toward the far end
    yaw = math.degrees(math.atan2(u[0], u[1])) % 360
    with open(os.path.join(out, "tb_skybridge.txt"), "w", newline="\n") as fh:
        fh.write('"skybridge";%.3f;%.3f;%.3f;0.000;0.000;1.000;%.3f;\n'
                 % (mid[0] + EASTING, mid[1], yaw, hm - sample(elev, *mid)))

    # clear the corridor under it in the other object lists
    removed = {}
    reach = half + 12.0
    for f in ("forest/tb_trees.txt", "forest/tb_bushes.txt", "forest/tb_deadwood.txt", "rocks/tb_rocks.txt",
              "buildings/tb_buildings.txt", "buildings/tb_cabins.txt", "buildings/tb_fences.txt"):
        p = os.path.join(os.path.dirname(out), f)
        keep, gone = [], 0
        for line in open(p):
            q = line.split(";")
            x, z = float(q[1]) - EASTING, float(q[2])
            d = np.array([x, z]) - mid
            along, across = float(d @ u), float(abs(d[0] * u[1] - d[1] * u[0]))
            if abs(along) <= reach and across <= CORRIDOR:
                gone += 1
                continue
            keep.append(line)
        if gone:
            with open(p, "w", newline="\n") as fh:
                fh.writelines(keep)
        removed[f] = gone

    s = ["Gatlinburg SkyBridge (OSM way %d)" % way["id"],
         "span %.1f m (the real bridge: 680 ft, 207 m), heading %.1f deg" % (span, yaw),
         "deck ends at %.1f m and %.1f m (ground at the OSM end points %.1f and %.1f), %.0f m ramps down to the ground beyond; sags %.1f m at mid-span"
         % (ha, hb, ground(-half), ground(half), RAMP, SAG),
         "deck stands %.1f m over the valley at its deepest (the real one: about 140 ft, 43 m)" % deepest,
         "lowest clearance between the towers: %.1f m" % clear,
         "model: %s, %d visual faces, %d collision components" % (path, len(vis.faces), comp[0]),
         "cleared from the corridor (%.0f m either side): %s" % (CORRIDOR, ", ".join("%s %d" % kv for kv in removed.items() if kv[1]))]
    open(os.path.join(out, "skybridge.txt"), "w", newline="\n").write("\n".join(s) + "\n")
    print("\n".join(s))


if __name__ == "__main__":
    main()
