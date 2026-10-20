"""Render a perspective view of the map with everything placed on it: terrain,
forest, bushes, rocks and cliffs, buildings, roads and creeks.

    python tools/render_view.py <out.jpg> [width height]

A software z-buffer renderer (numpy and PIL only), drawn at twice the size and
scaled down. The camera (VIEW) looks from above the hills north-west of
Gatlinburg to Mt. Le Conte; tools/topo_map.py uses it for the printed map's
title panel.

- Terrain: each column of pixels marches out along its ray over the heights,
  lit by a low sun from the west-south-west. The ground is forest floor, grass,
  building pads, roads and creeks painted at 2 m a pixel near the camera, and
  turns to its forest zone's canopy colour with distance.
- Trees and bushes: every placed one in view (out to 14 km and 3 km), as
  sprites sized from its model's height and crown width times its scale: spruce,
  pine and larch as dark cones, broadleaf trees as round crowns lit from the sun's
  side, on trunks.
- Rocks and cliffs as lit grey blobs, buildings as boxes from their models'
  bounding boxes (walls and roof).
- Haze by distance, a sky gradient, then scaled down.
"""

import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import find_models  # noqa: E402
from mission import MODEL_FOLDERS, ROAD_HALF_WIDTH, read_tb  # noqa: E402
from odol_info import odol_info  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "source")
SIZE = 20480.0
SS = 2                                        # supersampling
VIEW = {"cam": (2300.0, 17400.0), "height": 1180.0, "target": (10115.0, 7820.0), "fov": 62.0, "horizon": 0.30}
SUN_AZIMUTH, SUN_ELEVATION = 240.0, 32.0      # degrees: west-south-west, low afternoon sun
HAZE, HAZE_DIST = np.array((150, 172, 204), np.float32), 5200.0
SKY_TOP, SKY_LOW = np.array((98, 140, 196), np.float32), np.array((196, 210, 228), np.float32)
TREE_DIST, BUSH_DIST, ROCK_DIST, TEX_DIST, SHADOW_DIST = 14000.0, 3000.0, 9000.0, 9000.0, 5500.0
TEX_CELL = 2.0                                # near-field ground texture, metres a pixel

# Canopy colour by forest zone (open, spruce-fir, northern hardwood, cove, oak-pine, mixed).
CANOPY = np.array([(150, 146, 100), (34, 58, 40), (88, 108, 56), (70, 98, 48), (98, 104, 58), (82, 102, 52)],
                  np.float32)
FLOOR, GRASS = (56, 62, 40), (104, 120, 70)
PAD = {"cp_concrete1": (158, 156, 150), "cp_dirt": (134, 122, 98)}
ROAD = {"asf1": (78, 78, 80), "asf2": (80, 80, 82), "asf3": (86, 85, 84), "grav": (150, 138, 112),
        "mud": (128, 110, 84), "trail": (116, 98, 72)}
WATER = (58, 84, 96)
# Trees: template prefix, shape, summer colour.
SPECIES = [("t_piceaabies", "cone", (34, 58, 40)), ("t_pinussylvestris", "cone", (46, 66, 40)),
           ("t_larix", "cone", (72, 98, 50)), ("t_fagus", "crown", (78, 112, 46)),
           ("t_quercus", "crown", (68, 98, 40)), ("t_betula", "crown", (102, 130, 58)),
           ("t_acer", "crown", (76, 110, 44)), ("t_carpinus", "crown", (72, 104, 46)),
           ("t_fraxinus", "crown", (82, 112, 52)), ("t_populus", "crown", (92, 122, 60)),
           ("t_sorbus", "crown", (80, 110, 50)), ("t_juglans", "crown", (66, 96, 42)),
           ("t_robinia", "crown", (94, 124, 58)), ("t_salix", "crown", (104, 130, 74)),
           ("b_piceaabies", "cone", (40, 64, 42)), ("b_", "crown", (70, 100, 46)), ("t_", "crown", (76, 106, 48))]
TRUNK = np.array((66, 56, 44), np.float32)
ROCK, MOSS = np.array((128, 124, 116), np.float32), np.array((96, 108, 74), np.float32)
WALL = {"brick": (150, 92, 72), "shed": (146, 126, 98), "store": (206, 200, 188), "house": (196, 186, 166)}
ROOF = [(88, 80, 76), (120, 62, 52), (70, 74, 80), (104, 96, 84)]


# ---------------------------------------------------------------- camera and helpers

class Camera:
    def __init__(self, view, w, h):
        cx, cz = view["cam"]
        tx, tz = view["target"]
        self.pos = np.array([cx, view["height"], cz])
        psi = math.atan2(tx - cx, tz - cz)
        self.yaw = psi
        self.f = np.array([math.sin(psi), math.cos(psi)])          # forward and right, (x, z)
        self.r = np.array([math.cos(psi), -math.sin(psi)])
        self.half = math.radians(view["fov"]) / 2
        self.focal = (w / 2) / math.tan(self.half)
        self.cx, self.hy = w / 2, h * view["horizon"]
        self.w, self.h = w, h

    def project(self, x, y, z):
        dx, dy, dz = x - self.pos[0], y - self.pos[1], z - self.pos[2]
        depth = dx * self.f[0] + dz * self.f[1]
        lat = dx * self.r[0] + dz * self.r[1]
        with np.errstate(divide="ignore", invalid="ignore"):
            return self.cx + lat / depth * self.focal, self.hy - dy / depth * self.focal, depth

    def in_view(self, x, z, near, far, margin=50.0):
        dx, dz = x - self.pos[0], z - self.pos[2]
        depth = dx * self.f[0] + dz * self.f[1]
        lat = dx * self.r[0] + dz * self.r[1]
        return (depth > near) & (depth < far) & (np.abs(lat) < depth * math.tan(self.half) * 1.04 + margin)


def sample(grid, x, z, cell, centred=True):
    """Bilinear sample of a square map grid (rows south up) at map x, z. Image-like grids hold
    cell centres; the heights hold grid points at multiples of the cell, as build_world reads them."""
    n = grid.shape[0]
    off = 0.5 if centred else 0.0
    u = np.clip(np.asarray(x) / cell - off, 0, n - 1.001)
    v = np.clip(np.asarray(z) / cell - off, 0, n - 1.001)
    i, j = v.astype(np.int32), u.astype(np.int32)
    fu, fv = u - j, v - i
    if grid.ndim == 3:
        fu, fv = fu[..., None], fv[..., None]
    return (grid[i, j] * (1 - fu) * (1 - fv) + grid[i, j + 1] * fu * (1 - fv)
            + grid[i + 1, j] * (1 - fu) * fv + grid[i + 1, j + 1] * fu * fv)


def box_blur(a, r, passes=2):
    for _ in range(passes):
        for ax in (0, 1):
            p = np.pad(a, [(r + 1, r) if k == ax else (0, 0) for k in range(a.ndim)], mode="edge")
            cs = np.cumsum(p, axis=ax, dtype=np.float64)
            a = ((cs.take(np.arange(2 * r + 1, cs.shape[ax]), axis=ax)
                  - cs.take(np.arange(0, cs.shape[ax] - 2 * r - 1), axis=ax)) / (2 * r + 1)).astype(np.float32)
    return a


def slope_light(gx, gz, x, z, cell):
    """How much the ground at x, z faces the sun (0 to 1), from the smoothed height gradients."""
    sun = sun_vector()
    ggx, ggz = sample(gx, x, z, cell, centred=False), sample(gz, x, z, cell, centred=False)
    return np.clip((-ggx * sun[0] - ggz * sun[1] + sun[2]) / np.sqrt(ggx * ggx + ggz * ggz + 1), 0, 1)


def sun_vector():
    az, el = math.radians(SUN_AZIMUTH), math.radians(SUN_ELEVATION)
    return np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])   # x, z, up


class Frame:
    """Colour and depth buffers, flat, with a depth-tested write."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.rgb = np.zeros((h * w, 3), np.float32)
        self.z = np.full(h * w, np.inf, np.float32)

    def write(self, px, py, depth, colour):
        """Write pixels where they're nearer than what's there; among a batch's own
        overlapping pixels the nearest wins."""
        ok = (px >= 0) & (px < self.w) & (py >= 0) & (py < self.h)
        idx = py[ok].astype(np.int64) * self.w + px[ok].astype(np.int64)
        depth, colour = depth[ok].astype(np.float32), colour[ok]
        if idx.size > 200_000:
            nearest = self.z.copy()
            np.minimum.at(nearest, idx, depth)
            win = (depth == nearest[idx]) & (depth < self.z[idx])
        else:
            u, inv = np.unique(idx, return_inverse=True)
            best = np.full(u.size, np.inf, np.float32)
            np.minimum.at(best, inv, depth)
            win = (depth == best[inv]) & (depth < self.z[idx])
        self.z[idx[win]] = depth[win]
        self.rgb[idx[win]] = colour[win]


# ---------------------------------------------------------------- ground

def ground_texture(cam, footprints, roads, water):
    """RGBA texture at TEX_CELL m of the near field: forest floor or grass, pads, roads, creeks.
    Alpha 255 where the canopy colour must not cover it with distance (roads, rivers)."""
    pts = [cam.pos[[0, 2]]]
    for a in np.linspace(-cam.half * 1.05, cam.half * 1.05, 9):
        d = np.array([math.sin(cam.yaw + a), math.cos(cam.yaw + a)])
        pts.append(cam.pos[[0, 2]] + d * TEX_DIST / math.cos(min(abs(a), cam.half)))
    pts = np.array(pts)
    x0, z0 = np.clip(pts.min(0) - 50, 0, SIZE)
    x1, z1 = np.clip(pts.max(0) + 50, 0, SIZE)
    nx, nz = int((x1 - x0) / TEX_CELL), int((z1 - z0) / TEX_CELL)
    zones = np.load(os.path.join(SRC, "forest", "zones.npy"))[::-1]                 # south up, 8 m
    zc = SIZE / zones.shape[0]
    forest = Image.fromarray(box_blur((zones != 0).astype(np.float32), 1, 1))       # soft edges, scaled up
    forest = np.asarray(forest.resize((nx, nz), Image.BILINEAR, box=(x0 / zc, z0 / zc, x1 / zc, z1 / zc)))
    rgb = (np.array(GRASS, np.float32) * (1 - forest[..., None]) + np.array(FLOOR, np.float32) * forest[..., None])
    rng = np.random.default_rng(7)
    var = box_blur(rng.random((nz, nx), np.float32), 3, 2)
    var = 0.86 + 0.28 * (var - var.min()) / max(1e-6, var.max() - var.min())
    rgb = np.clip(rgb * var[..., None], 0, 255).astype(np.uint8)
    del forest, var
    im = Image.fromarray(np.dstack([rgb, np.zeros((nz, nx), np.uint8)]), "RGBA")
    dr = ImageDraw.Draw(im)

    def P(x, z):
        return ((x - x0) / TEX_CELL, (z - z0) / TEX_CELL)                          # row 0 = south edge
    for f in footprints:
        c = f["corners"]
        cx, cz = sum(p[0] for p in c) / 4, sum(p[1] for p in c) / 4
        grow = [(cx + (p[0] - cx) * 1.25, cz + (p[1] - cz) * 1.25) for p in c]   # the pad round it
        dr.polygon([P(*p) for p in grow], fill=PAD.get(f["surface"], PAD["cp_dirt"]) + (0,))
    for ln in water:
        wide = ln["class"] == "river"
        dr.line([P(*p) for p in ln["points"]], fill=WATER + ((255,) if wide else (0,)),
                width=max(1, int(round((9.0 if wide else 3.0) / TEX_CELL))), joint="curve")
    for ln in sorted(roads, key=lambda r: r["family"] == "trail", reverse=True):
        hw = ROAD_HALF_WIDTH.get(ln["family"], 1.2)
        dr.line([P(*p) for p in ln["points"]], fill=ROAD[ln["family"]] + (255,),
                width=max(1, int(round(2 * hw / TEX_CELL))), joint="curve")
    return np.asarray(im).astype(np.float32), (x0, z0)


def shadow_map(cam, origin, shape, plant_groups, building_groups):
    """Ground shadows (0 to 1) of the near trees, bushes and buildings, on the ground texture's grid."""
    x0, z0 = origin
    im = Image.new("L", (shape[1], shape[0]), 0)
    dr = ImageDraw.Draw(im)
    s = sun_vector()
    away = -np.array([s[0], s[1]]) / math.hypot(s[0], s[1])                       # shadows fall this way
    side = np.array([-away[1], away[0]])
    reach = 1 / math.tan(math.radians(SUN_ELEVATION))                             # metres along per metre up
    stretch = 1 / math.sin(math.radians(SUN_ELEVATION))
    t = np.linspace(0, 2 * math.pi, 11)[:-1]
    for tpl, rows, info in plant_groups:
        rows = rows[cam.in_view(rows[:, 0], rows[:, 1], 30.0, SHADOW_DIST)]
        if not len(rows):
            continue
        shape_, _ = next((sh, c) for p, sh, c in SPECIES if tpl.startswith(p))
        (mx0, my0, mz0), (mx1, my1, mz1) = info["min"], info["max"]
        H = (my1 - my0) * rows[:, 5]
        R = 0.5 * max(mx1 - mx0, mz1 - mz0) * rows[:, 5] * (0.6 if shape_ == "cone" else 0.75)
        hc = H * (0.40 if shape_ == "cone" else 0.64)
        cx = rows[:, 0] + away[0] * hc * reach
        cz = rows[:, 1] + away[1] * hc * reach
        px = (cx[:, None] + (R * stretch)[:, None] * np.cos(t) * away[0] + R[:, None] * np.sin(t) * side[0] - x0) / TEX_CELL
        pz = (cz[:, None] + (R * stretch)[:, None] * np.cos(t) * away[1] + R[:, None] * np.sin(t) * side[1] - z0) / TEX_CELL
        for a, b in zip(px, pz):
            dr.polygon(list(zip(a, b)), fill=255)
    for groups in building_groups:
        for tpl, rows, info in groups:
            (mx0, my0, mz0), (mx1, my1, mz1) = info["min"], info["max"]
            for r in rows:
                yaw, sc = math.radians(r[2]), r[5]
                ca, sa = math.cos(yaw), math.sin(yaw)
                foot = np.array([(r[0] + sc * (lx * ca + lz * sa), r[1] + sc * (-lx * sa + lz * ca))
                                 for lx, lz in ((mx0, mz0), (mx1, mz0), (mx1, mz1), (mx0, mz1))])
                tip = foot + away * (my1 - my0) * sc * reach
                for a in range(4):                                               # the walls' shadows
                    quad = [foot[a], foot[(a + 1) % 4], tip[(a + 1) % 4], tip[a]]
                    dr.polygon([((p[0] - x0) / TEX_CELL, (p[1] - z0) / TEX_CELL) for p in quad], fill=255)
    return box_blur(np.asarray(im, np.float32) / 255.0, 1, 1)


def terrain(cam, frame, elev, gx, gz, tex, tex_origin, canopy, forest_frac, shadow):
    cell = SIZE / elev.shape[0]
    depths = np.geomspace(25.0, 30000.0, 4600).astype(np.float32)
    w, h = cam.w, cam.h
    tx0, tz0 = tex_origin
    tn = tex.shape[:2]
    rgb = frame.rgb.reshape(h, w, 3)
    zb = frame.z.reshape(h, w)
    for c0 in range(0, w, 192):
        cols = np.arange(c0, min(w, c0 + 192))
        t = (cols + 0.5 - cam.cx) / cam.focal
        dirx = cam.f[0] + t * cam.r[0]
        dirz = cam.f[1] + t * cam.r[1]
        xs = cam.pos[0] + depths[None, :] * dirx[:, None]
        zs = cam.pos[2] + depths[None, :] * dirz[:, None]
        inside = (xs > 0) & (xs < SIZE - 6) & (zs > 0) & (zs < SIZE - 6)
        hh = sample(elev, xs, zs, cell, centred=False)
        shade = 0.34 + 1.02 * slope_light(gx, gz, xs, zs, cell)
        # Ground colour: the near texture, turning to canopy colour in forest with distance.
        u, v = (xs - tx0) / TEX_CELL - 0.5, (zs - tz0) / TEX_CELL - 0.5
        in_tex = (u >= 0) & (u < tn[1] - 1.001) & (v >= 0) & (v < tn[0] - 1.001)
        i, j = np.clip(v, 0, tn[0] - 1.001).astype(np.int32), np.clip(u, 0, tn[1] - 1.001).astype(np.int32)
        fu, fv = (np.clip(u, 0, None) - j)[..., None], (np.clip(v, 0, None) - i)[..., None]
        near = (tex[i, j] * (1 - fu) * (1 - fv) + tex[i, j + 1] * fu * (1 - fv)
                + tex[i + 1, j] * (1 - fu) * fv + tex[i + 1, j + 1] * fu * fv)
        can = sample(canopy, xs, zs, SIZE / canopy.shape[0])
        fr = sample(forest_frac, xs, zs, SIZE / forest_frac.shape[0])
        dist = depths[None, :]
        k = np.clip((dist - 1600.0) / 6400.0, 0, 1)
        k = k * k * (3 - 2 * k)
        keep = near[..., 3] / 255.0 * (1 - np.clip((dist - 7000.0) / 3000.0, 0, 1))
        base = np.where(in_tex[..., None], near[..., :3], np.where(fr[..., None] > 0.5, can, np.array(GRASS)))
        mix = np.where(in_tex, fr * k * (1 - keep), 1.0)[..., None]
        sh = (shadow[i, j] * (1 - fu[..., 0]) * (1 - fv[..., 0]) + shadow[i, j + 1] * fu[..., 0] * (1 - fv[..., 0])
              + shadow[i + 1, j] * (1 - fu[..., 0]) * fv[..., 0] + shadow[i + 1, j + 1] * fu[..., 0] * fv[..., 0])
        sh = np.where(in_tex, sh, 0) * (1 - np.clip((dist - 2500.0) / 3000.0, 0, 1))
        colour = (base * (1 - mix) + can * mix) * (shade * (1 - 0.55 * sh))[..., None]
        ys = np.floor(cam.hy - (hh - cam.pos[1]) / dist * cam.focal).astype(np.int64)
        ys[~inside] = h
        for n, c in enumerate(cols):
            y = np.clip(ys[n], 0, h)
            prev = np.minimum.accumulate(np.concatenate([[h], y[:-1]]))
            vis = y < prev
            if not vis.any():
                continue
            starts, ends = y[vis], prev[vis]
            lens = ends - starts
            total = int(lens.sum())
            rows = np.repeat(ends, lens) - (np.arange(total) - np.repeat(np.cumsum(lens) - lens, lens)) - 1
            rgb[rows, c] = np.repeat(colour[n][vis], lens, axis=0)
            zb[rows, c] = np.repeat(depths[vis], lens)
        print("terrain columns %d / %d" % (cols[-1] + 1, w), flush=True)


# ---------------------------------------------------------------- sprites

def light_screen(cam):
    """The sun as seen from the camera: x right, y up, z towards the viewer."""
    s = sun_vector()
    return np.array([s[0] * cam.r[0] + s[1] * cam.r[1], s[2], -(s[0] * cam.f[0] + s[1] * cam.f[1])])


def noise_field(w, h, seed=3):
    rng = np.random.default_rng(seed)
    n = box_blur(rng.random((h // 2 + 2, w // 2 + 2), np.float32), 1, 1)
    n = np.repeat(np.repeat(n, 2, 0), 2, 1)[:h, :w]
    n = (n - n.mean()) / max(1e-6, n.std())
    return n.astype(np.float32).ravel()


def draw_ellipses(frame, cam, noise, xc, cy, rx, ry, depth, colour, ambient=0.42, diffuse=0.78, ao=0.22):
    """Lit round crowns (or rock blobs): centre xc, cy, radii rx, ry in pixels."""
    L = light_screen(cam)
    rx, ry = np.maximum(rx, 0.55), np.maximum(ry, 0.55)
    budget = 6_000_000
    cum = np.cumsum(np.pi * (rx + 1) * (ry + 1))
    edges = list(range(0, int(cum[-1]) + budget, budget))
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = np.nonzero((cum > lo) & (cum <= hi))[0]
        if not sel.size:
            continue
        r0 = np.floor(cy[sel] - ry[sel]).astype(np.int64)
        r1 = np.ceil(cy[sel] + ry[sel]).astype(np.int64)
        nr = np.maximum(r1 - r0, 1)
        sid = np.repeat(np.arange(sel.size), nr)
        row = r0[sid] + (np.arange(sid.size) - np.repeat(np.cumsum(nr) - nr, nr))
        s = sel[sid]
        v = (row + 0.5 - cy[s]) / ry[s]
        keep = np.abs(v) < 1
        sid, row, s, v = sid[keep], row[keep], s[keep], v[keep]
        half = rx[s] * np.sqrt(1 - v * v)
        x0 = np.round(xc[s] - half).astype(np.int64)
        x1 = np.round(xc[s] + half).astype(np.int64)
        nl = np.maximum(x1 - x0, 1)
        pid = np.repeat(np.arange(row.size), nl)
        px = x0[pid] + (np.arange(pid.size) - np.repeat(np.cumsum(nl) - nl, nl))
        py = row[pid]
        sp = s[pid]
        uu = np.clip((px + 0.5 - xc[sp]) / rx[sp], -1, 1)
        vv = v[pid]
        nz = np.sqrt(np.clip(1 - uu * uu - vv * vv, 0, 1))
        lit = ambient + diffuse * np.clip(uu * L[0] - vv * L[1] + nz * L[2], 0, 1)
        lit *= 1 - ao * np.clip(vv, 0, 1)                                        # darker underneath
        ok = (px >= 0) & (px < frame.w) & (py >= 0) & (py < frame.h)
        tex = np.ones(px.size, np.float32)
        tex[ok] = 1 + 0.10 * noise[(py[ok] * frame.w + px[ok])]
        frame.write(px, py, depth[sp], colour[sp] * (lit * tex)[:, None])


def draw_cones(frame, cam, noise, xc, ytop, ybot, hw, depth, colour):
    """Conifers: a cone from ytop to ybot, hw pixels across at its base."""
    L = light_screen(cam)
    hw = np.maximum(hw, 0.55)
    budget = 6_000_000
    est = (ybot - ytop + 1) * (hw + 1)
    cum = np.cumsum(est)
    edges = list(range(0, int(cum[-1]) + budget, budget))
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = np.nonzero((cum > lo) & (cum <= hi))[0]
        if not sel.size:
            continue
        r0 = np.floor(ytop[sel]).astype(np.int64)
        r1 = np.ceil(ybot[sel]).astype(np.int64)
        nr = np.maximum(r1 - r0, 1)
        sid = np.repeat(np.arange(sel.size), nr)
        row = r0[sid] + (np.arange(sid.size) - np.repeat(np.cumsum(nr) - nr, nr))
        s = sel[sid]
        t = np.clip((row + 0.5 - ytop[s]) / np.maximum(ybot[s] - ytop[s], 1e-3), 0, 1)   # 0 top, 1 base
        half = hw[s] * (0.08 + 0.92 * t ** 0.9)
        x0 = np.round(xc[s] - half).astype(np.int64)
        x1 = np.round(xc[s] + half).astype(np.int64)
        nl = np.maximum(x1 - x0, 1)
        pid = np.repeat(np.arange(row.size), nl)
        px = x0[pid] + (np.arange(pid.size) - np.repeat(np.cumsum(nl) - nl, nl))
        py = row[pid]
        sp = s[pid]
        uu = np.clip((px + 0.5 - xc[sp]) / np.maximum(half[pid], 0.5), -1, 1)
        nz = np.sqrt(1 - uu * uu)
        lit = 0.40 + 0.80 * np.clip(uu * L[0] * 0.95 + 0.30 * L[1] + nz * L[2] * 0.95, 0, 1)
        lit *= 1 - 0.30 * t[pid]                                                 # darker low branches
        ok = (px >= 0) & (px < frame.w) & (py >= 0) & (py < frame.h)
        tex = np.ones(px.size, np.float32)
        tex[ok] = 1 + 0.12 * noise[(py[ok] * frame.w + px[ok])]
        frame.write(px, py, depth[sp], colour[sp] * (lit * tex)[:, None])


def draw_trunks(frame, xc, ytop, ybot, wpx, depth):
    keep = (ybot - ytop >= 1) & (wpx >= 0.6)
    xc, ytop, ybot, wpx, depth = xc[keep], ytop[keep], ybot[keep], wpx[keep], depth[keep]
    if not xc.size:
        return
    r0, r1 = np.floor(ytop).astype(np.int64), np.ceil(ybot).astype(np.int64)
    nr = np.maximum(r1 - r0, 1)
    sid = np.repeat(np.arange(xc.size), nr)
    row = r0[sid] + (np.arange(sid.size) - np.repeat(np.cumsum(nr) - nr, nr))
    hw = np.maximum(wpx[sid] / 2, 0.5)
    x0 = np.round(xc[sid] - hw).astype(np.int64)
    nl = np.maximum(np.round(2 * hw).astype(np.int64), 1)
    pid = np.repeat(np.arange(row.size), nl)
    px = x0[pid] + (np.arange(pid.size) - np.repeat(np.cumsum(nl) - nl, nl))
    frame.write(px, row[pid], depth[sid][pid], np.repeat(TRUNK[None, :], px.size, 0))


# ---------------------------------------------------------------- objects

class Models:
    def __init__(self):
        self.paths = find_models(MODEL_FOLDERS)
        self.info = {}

    def __call__(self, tpl):
        if tpl not in self.info:
            self.info[tpl] = odol_info(os.path.join("P:\\", self.paths[tpl]))
        return self.info[tpl]


def load_objects(path, cam, far, models):
    """Placed objects in view: (template, rows) per template, rows x, z, yaw, scale, model info."""
    codes = {}
    c, rows = read_tb(path, codes)
    keep = cam.in_view(rows[:, 0], rows[:, 1], 30.0, far)
    c, rows = c[keep], rows[keep]
    names = {v: k for k, v in codes.items()}
    out = []
    for code in np.unique(c):
        tpl = names[code]
        out.append((tpl, rows[c == code], models(tpl)))
    return out


def plants(frame, cam, noise, groups, elev, gx, gz, rng, kind):
    cell = SIZE / elev.shape[0]
    cones, crowns = [], []
    for tpl, rows, info in groups:
        shape, col = next((s, c) for p, s, c in SPECIES if tpl.startswith(p))
        (mx0, my0, mz0), (mx1, my1, mz1) = info["min"], info["max"]
        H = (my1 - my0) * rows[:, 5]
        R = 0.5 * max(mx1 - mx0, mz1 - mz0) * rows[:, 5] * (0.72 if shape == "cone" else 0.80)
        x, z = rows[:, 0], rows[:, 1]
        g = sample(elev, x, z, cell, centred=False)
        jit = (1 + 0.10 * rng.standard_normal((len(x), 3))) * (1 + 0.08 * rng.standard_normal((len(x), 1)))
        jit *= (0.55 + 0.62 * slope_light(gx, gz, x, z, cell))[:, None]        # shaded slopes, darker trees
        c = np.clip(np.array(col, np.float32)[None, :] * jit, 0, 255)
        (cones if shape == "cone" else crowns).append((x, z, g, H, R, c))
    for shape, parts in (("cone", cones), ("crown", crowns)):
        if not parts:
            continue
        x, z, g, H, R, c = (np.concatenate([p[k] for p in parts]) for k in range(6))
        sx, sb, depth = cam.project(x, g, z)
        _, st, _ = cam.project(x, g + H, z)
        rpx = R / depth * cam.focal
        dtest = (depth - R).astype(np.float32)
        if shape == "cone":
            ybot = st + (sb - st) * (0.92 if kind == "tree" else 1.0)
            draw_cones(frame, cam, noise, sx, st, ybot, rpx, dtest, c)
            draw_trunks(frame, sx, ybot, sb, np.maximum(rpx * 0.10, 0.7), dtest + R * 0.6)
        else:
            if kind == "tree":
                cy, ry = st + (sb - st) * 0.36, (sb - st) * 0.36
                draw_trunks(frame, sx, cy + ry * 0.6, sb, np.maximum(rpx * 0.12, 0.7), dtest + R * 0.6)
            else:
                cy, ry = st + (sb - st) * 0.5, (sb - st) * 0.5
            draw_ellipses(frame, cam, noise, sx, cy, rpx, ry, dtest, c)
        print("%s %ss drawn: %d" % (kind, shape, len(x)), flush=True)


def rocks(frame, cam, noise, groups, elev, gx, gz):
    cell = SIZE / elev.shape[0]
    xs, cys, rxs, rys, ds, cs = [], [], [], [], [], []
    for tpl, rows, info in groups:
        if not tpl.startswith("rock_"):                                  # boulders: only close by
            rows = rows[cam.in_view(rows[:, 0], rows[:, 1], 30.0, 2500.0)]
        if not len(rows):
            continue
        (mx0, my0, mz0), (mx1, my1, mz1) = info["min"], info["max"]
        s = rows[:, 5]
        R = 0.5 * max(mx1 - mx0, mz1 - mz0) * s
        x, z = rows[:, 0], rows[:, 1]
        ground = sample(elev, x, z, cell, centred=False)
        top = ground + rows[:, 6] + my1 * s                              # the model's origin is ground + rel
        bottom = np.maximum(ground + rows[:, 6] + my0 * s, ground)       # what shows above the ground
        sx, sc, depth = cam.project(x, (top + bottom) / 2, z)
        _, st, _ = cam.project(x, top, z)
        col = MOSS if "moss" in tpl else ROCK
        xs.append(sx); cys.append(sc); rys.append(np.abs(sc - st))
        rxs.append(R / depth * cam.focal); ds.append((depth - R).astype(np.float32))
        cs.append(col[None, :] * (0.6 + 0.55 * slope_light(gx, gz, x, z, cell))[:, None])
    if xs:
        draw_ellipses(frame, cam, noise, *(np.concatenate(a) for a in (xs, cys, rxs, rys, ds, cs)),
                      ambient=0.38, diffuse=0.85, ao=0.15)


def wall_colour(tpl):
    if "b0" in tpl or "brick" in tpl:
        return WALL["brick"]
    if tpl.startswith(("shed", "barn", "farm", "garage")):
        return WALL["shed"]
    if tpl.startswith(("city_", "hotel", "office", "houseblock", "tenement", "village_store", "fuelstation")):
        return WALL["store"]
    return WALL["house"]


def buildings(frame, cam, groups, elev):
    cell = SIZE / elev.shape[0]
    sun = sun_vector()
    n = 0
    for tpl, rows, info in groups:
        (mx0, my0, mz0), (mx1, my1, mz1) = info["min"], info["max"]
        wall = np.array(wall_colour(tpl), np.float32)
        for k, r in enumerate(rows):
            x, z, yaw, s = r[0], r[1], math.radians(r[2]), r[5]
            g = float(sample(elev, x, z, cell, centred=False))
            y0, y1 = g + r[6] + my0 * s, g + r[6] + my1 * s
            ca, sa = math.cos(yaw), math.sin(yaw)
            foot = [(x + s * (lx * ca + lz * sa), z + s * (-lx * sa + lz * ca))
                    for lx, lz in ((mx0, mz0), (mx1, mz0), (mx1, mz1), (mx0, mz1))]
            roof = np.array(ROOF[(len(tpl) + k) % len(ROOF)], np.float32)
            faces = []
            for a in range(4):
                (ax, az), (bx, bz) = foot[a], foot[(a + 1) % 4]
                nx, nz = bz - az, -(bx - ax)                                     # outward for this winding
                cxm, czm = (ax + bx) / 2 - x, (az + bz) / 2 - z
                if nx * cxm + nz * czm < 0:
                    nx, nz = -nx, -nz
                ln = math.hypot(nx, nz) or 1.0
                nx, nz = nx / ln, nz / ln
                if nx * (cam.pos[0] - (ax + bx) / 2) + nz * (cam.pos[2] - (az + bz) / 2) <= 0:
                    continue
                lit = 0.45 + 0.75 * max(0.0, nx * sun[0] + nz * sun[1])
                faces.append(([(ax, y0, az), (bx, y0, bz), (bx, y1, bz), (ax, y1, az)], wall * lit))
            faces.append(([(p[0], y1, p[1]) for p in foot], roof * (0.55 + 0.6 * sun[2])))
            for poly, colour in faces:
                P = np.array(poly)
                sx, sy, d = cam.project(P[:, 0], P[:, 1], P[:, 2])
                if (d < 30).any():
                    continue
                bx0, by0 = int(math.floor(sx.min())), int(math.floor(sy.min()))
                bx1, by1 = int(math.ceil(sx.max())) + 1, int(math.ceil(sy.max())) + 1
                if bx1 < 0 or by1 < 0 or bx0 >= frame.w or by0 >= frame.h:
                    continue
                mask = Image.new("1", (bx1 - bx0 + 1, by1 - by0 + 1), 0)
                ImageDraw.Draw(mask).polygon([(a - bx0, b - by0) for a, b in zip(sx, sy)], fill=1)
                yy, xx = np.nonzero(np.asarray(mask))
                if not xx.size:
                    continue
                depth = np.full(xx.size, float(d.mean()) - 0.5, np.float32)
                frame.write(xx + bx0, yy + by0, depth, np.repeat(colour[None, :], xx.size, 0))
            n += 1
    print("buildings drawn: %d" % n, flush=True)


# ---------------------------------------------------------------- the view

def render(out_jpg, w=2400, h=2358, view=VIEW):
    W, H = w * SS, h * SS
    cam = Camera(view, W, H)
    frame = Frame(W, H)
    elev = np.load(os.path.join(SRC, "buildings", "elevation.npy")).astype(np.float32)     # row 0 south, 5 m
    zones = np.load(os.path.join(SRC, "forest", "zones.npy"))[::-1]
    sat = np.asarray(Image.open(os.path.join(SRC, "satellite_preview.png")).convert("L"), np.float32)[::-1] / 255.0
    canopy = CANOPY[zones]
    canopy = np.stack([box_blur(canopy[..., k], 3, 2) for k in range(3)], -1)
    detail = np.asarray(Image.fromarray(np.clip(1.0 + 0.9 * (sat - box_blur(sat, 4, 2)), 0.7, 1.3).astype(np.float32))
                        .resize(canopy.shape[:2][::-1], Image.BILINEAR))
    canopy *= detail[..., None]
    forest_frac = box_blur((zones != 0).astype(np.float32), 2, 2)
    footprints = json.load(open(os.path.join(SRC, "buildings", "footprints.json")))
    roads = json.load(open(os.path.join(SRC, "roads", "lines.json")))
    water = json.load(open(os.path.join(SRC, "water", "lines.json")))
    tex, origin = ground_texture(cam, footprints, roads, water)
    print("ground texture %d x %d" % tex.shape[1::-1], flush=True)

    models = Models()
    houses = [load_objects(os.path.join(SRC, "buildings", f), cam, TREE_DIST, models)
              for f in ("tb_buildings.txt", "tb_cabins.txt", "tb_fuel.txt")]
    bushes = load_objects(os.path.join(SRC, "forest", "tb_bushes.txt"), cam, BUSH_DIST, models)
    trees = load_objects(os.path.join(SRC, "forest", "tb_trees.txt"), cam, TREE_DIST, models)
    shadow = shadow_map(cam, origin, tex.shape, trees + bushes, houses)
    print("shadows drawn", flush=True)

    sky_t = np.clip(np.linspace(0, 1, H)[:, None] / 0.36, 0, 1)
    sky = SKY_TOP * (1 - sky_t) + SKY_LOW * sky_t
    frame.rgb.reshape(H, W, 3)[:] = sky[:, None, :]
    gz, gx = np.gradient(box_blur(elev, 1, 2), SIZE / elev.shape[0])
    terrain(cam, frame, elev, gx, gz, tex, origin, canopy, forest_frac, shadow)
    del tex, shadow

    rng = np.random.default_rng(11)
    noise = noise_field(W, H)
    for groups in houses:
        buildings(frame, cam, groups, elev)
    rocks(frame, cam, noise, load_objects(os.path.join(SRC, "rocks", "tb_rocks.txt"), cam, ROCK_DIST, models), elev, gx, gz)
    plants(frame, cam, noise, bushes, elev, gx, gz, rng, "bush")
    plants(frame, cam, noise, trees, elev, gx, gz, rng, "tree")

    # Haze by distance over everything that isn't sky.
    z = frame.z
    solid = np.isfinite(z)
    hz = (1 - np.exp(-z[solid] / HAZE_DIST))[:, None] * 0.9
    frame.rgb[solid] = frame.rgb[solid] * (1 - hz) + HAZE[None, :] * hz
    img = Image.fromarray(np.clip(frame.rgb.reshape(H, W, 3), 0, 255).astype(np.uint8))
    img = img.resize((w, h), Image.LANCZOS)
    img.save(out_jpg, quality=92, subsampling=0)
    print("wrote %s (%d x %d)" % (out_jpg, w, h), flush=True)


def main():
    out = sys.argv[1]
    w, h = (int(v) for v in sys.argv[2:4]) if len(sys.argv) >= 4 else (2400, 2358)
    render(out, w, h)


if __name__ == "__main__":
    main()
