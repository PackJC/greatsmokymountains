"""Write the server mission for the map: where players, vehicles, animals,
infected, mushrooms and heli crashes spawn, and what loot is worth where.

    python tools/mission.py <vanilla mission> <out mission folder>

<vanilla mission> is DayZServer\\mpmissions\\dayzOffline.chernarusplus. It is
copied (without storage_*) and these files are replaced with ones for this map:
  areaflags.map             loot tiers by height; usage (Town, Village, Hunting,
                            Farm, Industrial, Police, ...) by what is nearby, and the
                            usages with no buildings here (ContaminatedArea, Prison,
                            Lunapark) where their loot fits
  mapgrouppos.xml           every placed building that has loot
  mapclusterproto.xml       vanilla plus clusters for this map's tree and dead wood models
  mapgroupcluster*.xml      mushrooms: under spruce and pine (Boletus, Macrolepiota),
                            beech, oak and birch (Lactarius), on fallen logs (Agaricus, Pleurotus);
                            apples, pears and plums under their trees; elderberries and
                            rose hips on their bushes; small stones along the trail parts
  cfgeventspawns.xml        vehicles, heli crashes, supply crates, police wrecks,
                            bonfires, plank piles, Christmas trees, Santa's sleigh,
                            military convoys and police scenes
  cfgeventgroups.xml        the convoys' and police scenes' layouts, on this map's roads
  cfgplayerspawnpoints.xml  fresh, hop and travel spawn areas
  env/*_territories.xml     animals and infected
  cfgeffectarea.json        no contaminated zones; safe positions on this map
  db/events.xml             events with nothing to spawn on here switched off, more heli crashes,
                            the berry events on, more fruit, mushrooms and berries out at once
  cfggameplay.json          climate: Gatlinburg's monthly temperatures
It reads source/: heights (buildings/elevation.npy), every Terrain Builder object
file (to keep spawns out of trees, rocks, walls and water), roads, water lines,
forest zones and mission/osm_places.json (OSM places, parking, campsites).

Spawn spots are checked against a 2 m occupancy grid of every placed object:
trees and bushes by their trunk, everything else by its model's bounding box.
"""

import argparse
import json
import math
import os
import random
import re
import shutil
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import bilinear, find_models  # noqa: E402
from geo import utm  # noqa: E402
from odol_info import odol_info  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "source")
SIZE = 20480.0
EASTING = 200000.0
SEED = 20261015
OCC = 2.0                                    # occupancy grid cell (m)
FLAGS = 4096                                 # areaflags.map pixels per side
MODEL_FOLDERS = [r"P:\DZ\structures\roads", r"P:\DZ\structures\residential", r"P:\DZ\structures\industrial",
                 r"P:\DZ\structures\specific", r"P:\DZ\structures\walls", r"P:\DZ\structures_bliss\residential",
                 r"P:\DZ\structures_bliss\industrial", r"P:\DZ\structures_bliss\roads\bridges",
                 r"P:\DZ\structures_bliss\walls", r"P:\DZ\water", r"P:\DZ\rocks", r"P:\DZ\rocks_bliss",
                 r"P:\DZ\plants\tree", r"P:\DZ\plants\bush", r"P:\DZ\plants_bliss\tree", r"P:\DZ\plants_bliss\bush",
                 r"P:\DZ\structures\signs\tourist", r"P:\DZ\water_sakhal\fresh",
                 r"P:\greatsmokymountains\data\skybridge", r"P:\greatsmokymountains\data\trailsigns",
                 r"P:\greatsmokymountains\data\footbridges"]
OBSTACLE_FILES = ["water/tb_water.txt", "rocks/tb_rocks.txt", "forest/tb_trees.txt", "forest/tb_bushes.txt",
                  "forest/tb_deadwood.txt", "buildings/tb_buildings.txt", "buildings/tb_cabins.txt",
                  "buildings/tb_fuel.txt", "buildings/tb_fences.txt", "buildings/tb_bridges.txt",
                  "buildings/tb_skybridge.txt"]
DETAIL_FILES = ["details/tb_markers.txt", "details/tb_signs.txt", "details/tb_props.txt", "details/tb_orchards.txt",
                "details/tb_footbridges.txt", "details/tb_lifts.txt", "details/tb_street.txt", "details/tb_power.txt",
                "details/tb_nature.txt"]
BUILDING_FILES = ["buildings/tb_buildings.txt", "buildings/tb_cabins.txt", "buildings/tb_fuel.txt"]
# Object lists whose models can carry clusters (mushrooms, fruit, berries, stones).
CLUSTER_SOURCES = ["forest/tb_trees.txt", "forest/tb_deadwood.txt", "forest/tb_bushes.txt",
                   "details/tb_orchards.txt", "details/tb_nature.txt", "roads/tb_trails.txt"]
ROAD_HALF_WIDTH = {"asf1": 6.0, "asf2": 4.5, "asf3": 3.5, "grav": 3.0, "mud": 2.5}

# Building kinds, by template prefix.
KINDS = [("police", ("city_policestation", "village_policestation")),
         ("fire", ("city_firestation",)),
         ("medic", ("village_healthcare", "city_hospital", "city_clinic")),
         ("church", ("church", "chapel")),
         ("school", ("city_school",)),
         ("office", ("office",)),
         ("industrial", ("garage_", "repair_center", "workshop", "fuelstation_")),
         ("farm", ("barn_", "farm_")),
         ("shed", ("shed_",))]

# Clusters: which placed models get them, and what grows there (db/events.xml's Trajectory
# events). Mushrooms under trees and on dead wood, fruit under the apple, pear and plum trees,
# berries on elder and dog rose, and small stones along the dirt and rock trail parts.
CLUSTERS = [("TrajectoryConiferous", ("t_piceaabies_", "t_pinussylvestris_", "d_piceaabies_", "d_pinussylvestris_")),
            ("TrajectoryHumus", ("d_fagussylvatica_fallen", "d_quercusrobur_fallen", "d_betulapendula_fallen")),
            ("TrajectoryDeciduous", ("t_fagussylvatica_", "t_quercusrobur_", "t_betulapendulae_", "t_carpinus_",
                                     "t_acer_", "d_fagussylvatica_stump", "d_quercusrobur_stump",
                                     "d_betulapendula_stump")),
            ("TrajectoryApple", ("t_malusdomestica_",)),
            ("TrajectoryPear", ("t_pyruscommunis_",)),
            ("TrajectoryPlum", ("t_prunusdomestica_",)),
            ("TrajectorySambucus", ("b_sambucusnigra_",)),
            ("TrajectoryCanina", ("b_rosacanina_",)),
            ("TrajectoryStones", ("path_dirt_", "path_rock_"))]
# Share of each kind of model given a cluster, first match: all dead wood and fruit trees, some
# living trees, berry bushes (elder grows by the hundred thousand here) and trail parts.
CLUSTER_SHARE = [("d_", 1.0), ("t_malusdomestica_", 1.0), ("t_pyruscommunis_", 1.0), ("t_prunusdomestica_", 1.0),
                 ("t_piceaabies_2d", 1.0), ("t_piceaabies_3d", 1.0), ("t_piceaabies_", 0.125),
                 ("t_pinussylvestris_", 0.125), ("t_", 0.05), ("b_rosacanina_", 0.35), ("b_sambucusnigra_", 0.1),
                 ("path_", 0.25)]
# The berry events vanilla keeps switched off, and how many of each Trajectory event's items are
# out at once (vanilla 140 and 100 for stones, on a map 1.8 times Chernarus).
BERRY_EVENTS = ["TrajectoryCanina", "TrajectorySambucus"]
MUSHROOM_EVENTS = ("TrajectoryConiferous", "TrajectoryHumus", "TrajectoryDeciduous")
TRAJECTORY_NOMINAL = {"TrajectoryStones": 180}
TRAJECTORY_NOMINAL_DEFAULT = 250

# Event order and the zone line of events that have one: as vanilla writes them.
ZONE = {"StaticHeliCrash": '<zone smin="1" smax="3" dmin="3" dmax="5" r="45" />',
        "StaticSantaCrash": '<zone smin="1" smax="1" dmin="1" dmax="1" r="45" />',
        "StaticBonfire": '<zone smin="3" smax="5" dmin="3" dmax="5" r="55" />',
        "StaticPoliceCar": '<zone smin="1" smax="3" dmin="3" dmax="5" r="45" />',
        "StaticAirplaneCrate": '<zone smin="0" smax="0" dmin="0" dmax="0" r="0" />',
        "StaticMilitaryConvoy": '<zone smin="0" smax="0" dmin="1" dmax="1" r="20" />',
        "StaticPoliceSituation": '<zone smin="0" smax="0" dmin="1" dmax="2" r="20" />'}
# Events with nothing to spawn on this map (no rails, no lakes, no gas).
SWITCH_OFF = ["StaticTrain", "StaticContaminatedArea", "VehicleBoat"]
HELI_CRASHES_AT_ONCE = 5                     # vanilla 3, on a map 1.8 times the size of Chernarus
# Heli crash and supply drop spots favour the high country: weight by tier when ordering them.
WILD_TIER_WEIGHT = {1: 0.5, 2: 1.0, 3: 2.0, 4: 3.0}
# Military convoys and police scenes (roadblocks, crashes, abandoned cars at trailheads), laid out on
# this map's roads and parking (cfgeventgroups.xml): spots per tier, most of them up the mountain roads.
CONVOYS = {1: 2, 2: 3, 3: 5, 4: 6}
SITUATIONS = {1: 5, 2: 5, 3: 6, 4: 6}
CONVOY_WRECKS = ["StaticObj_Wreck_Ural_DE", "Land_Wreck_V3S_DE", "StaticObj_Wreck_BMP2_DE", "StaticObj_Wreck_BRDM_DE",
                 "StaticObj_Wreck_Uaz_DE", "Land_wreck_truck01_aban1_green_DE", "Land_wreck_truck01_aban2_green_DE",
                 "Land_Wreck_offroad02_aban1_DE", "Land_Wreck_offroad02_aban2_DE"]
CIVIL_WRECKS = ["Land_Wreck_hb01_aban1_blue_DE", "Land_Wreck_hb01_aban1_green_DE", "Land_Wreck_hb01_aban2_white_DE",
                "Land_Wreck_hb02_aban1_red_DE", "Land_Wreck_hb02_aban2_black_DE", "Land_Wreck_sed01_aban1_white_DE",
                "Land_Wreck_sed01_aban2_wine_DE", "Land_Wreck_sed02_aban1_grey_DE", "Land_Wreck_sed02_aban2_red_DE"]
POLICE_WRECKS = ["Land_Wreck_sed01_aban1_police_DE", "Land_Wreck_sed01_aban2_police_DE",
                 "Land_Wreck_hb01_aban1_police_DE", "Land_Wreck_hb01_aban2_police_DE"]
SCENE_PLACES = ("amenity=parking", "highway=trailhead", "tourism=viewpoint")
OPEN_LANE = 3.0                              # road kept clear beside a convoy or police scene (m)
# Footprints (width, length in m) of the wrecks, from their models; roadblocks are long across.
WRECK_SIZE = {"BMP2": (3.9, 6.8), "BRDM": (2.9, 5.6), "Ural": (3.6, 7.3), "Uaz": (2.5, 3.7), "T72_Chassis": (5.3, 7.6),
              "T72_Turret": (4.6, 7.7), "V3S": (3.5, 8.8), "offroad02": (2.7, 4.9), "truck01": (2.7, 6.8),
              "hb01": (2.8, 5.8), "hb02": (2.6, 5.8), "sed01": (3.9, 6.5), "sed02": (2.8, 6.5),
              "Roadblock_Wood_Long": (3.1, 0.8)}

USAGE = {name: bit for bit, name in enumerate(
    ["Military", "Police", "Medic", "Firefighter", "Industrial", "Farm", "Coast", "Town", "Village", "Hunting",
     "Office", "School", "Prison", "Lunapark", "SeasonalEvent", "ContaminatedArea", "Historical"])}
TIER_HEIGHTS = (560.0, 900.0, 1400.0)        # Tier1 below the first, Tier4 above the last
HUNTING_PLACES = ("tourism=camp_site", "amenity=shelter", "highway=trailhead", "amenity=ranger_station",
                  "tourism=alpine_hut", "tourism=picnic_site", "tourism=viewpoint")
CLUSTERS_PER_FILE, CLUSTER_FILES = 50000, 8
# Gatlinburg (about 400 m) monthly normals, degrees C. This world gets the game's
# ChernarusPlusData, which takes 0.012 C per metre of height off cfggameplay's base
# temperatures; the offset makes 800 m, between the towns and the median ground
# (967 m), come out at the real temperature there (6.5 C per km above Gatlinburg).
# Gatlinburg runs 2 C warm, Le Conte's summit 7 C cold.
CLIMATE_MIN = [-3.9, -2.5, 0.8, 5.0, 10.3, 14.9, 17.3, 16.8, 13.3, 6.5, 1.5, -2.3]
CLIMATE_MAX = [9.4, 12.0, 16.5, 21.5, 25.4, 28.7, 30.2, 29.8, 27.0, 21.8, 16.0, 10.7]
CLIMATE_OFFSET = 0.012 * 800 - 0.0065 * (800 - 400)


# ---------------------------------------------------------------- reading

def read_tb(path, codes):
    """Terrain Builder object file -> template codes, rows (x, z, yaw, pitch, roll, scale, rel)."""
    n = sum(1 for _ in open(path))
    rows = np.empty((n, 7))
    c = np.empty(n, np.int32)
    k = 0
    for line in open(path):
        p = line.strip().rstrip(";").split(";")
        if len(p) < 8:
            continue
        c[k] = codes.setdefault(p[0].strip().strip('"').lower(), len(codes))
        rows[k] = [float(v) for v in p[1:8]]
        k += 1
    rows = rows[:k]
    rows[:, 0] -= EASTING
    return c[:k], rows


def osm_places():
    geo = json.load(open(os.path.join(ROOT, "tools", "georef.json")))
    out = []
    for e in json.load(open(os.path.join(SRC, "mission", "osm_places.json"), encoding="utf-8"))["elements"]:
        p = e.get("center") or ({"lat": e["lat"], "lon": e["lon"]} if "lat" in e else None)
        if not p:
            continue
        x, z = utm(p["lat"], p["lon"], 17)
        x, z = x + geo["offset_x"], z + geo["offset_y"]
        if not (50 <= x <= SIZE - 50 and 50 <= z <= SIZE - 50):
            continue
        t = e["tags"]
        kind = next((k + "=" + t[k] for k in ("place", "amenity", "tourism", "highway", "natural", "landuse",
                                               "leisure", "historic") if k in t), "")
        out.append({"kind": kind, "name": t.get("name", ""), "x": x, "z": z})
    return out


def kind_of(tpl):
    for kind, prefixes in KINDS:
        if tpl.startswith(prefixes):
            return kind
    return "house"


# ---------------------------------------------------------------- geometry helpers

class Terrain:
    def __init__(self, elev):
        self.elev = elev
        self.cell = SIZE / elev.shape[0]
        gz, gx = np.gradient(elev.astype(np.float32), self.cell)
        self.slope = np.hypot(gx, gz)

    def h(self, x, z):
        return bilinear(self.elev, x / self.cell, z / self.cell)

    def steep(self, x, z, r=0.0):
        """Steepest slope (rise over run) within r of (x, z)."""
        k = max(1, int(math.ceil(r / self.cell)))
        i, j = int(z / self.cell), int(x / self.cell)
        w = self.slope[max(0, i - k):i + k + 1, max(0, j - k):j + k + 1]
        return float(w.max()) if w.size else 9.0


class Occupancy:
    """2 m grid: bit 1 tree or bush trunk, bit 2 anything else (bounding boxes)."""

    def __init__(self):
        n = int(SIZE / OCC)
        self.g = np.zeros((n, n), np.uint8)

    def mark(self, x, z, bit):
        i = np.clip((z / OCC).astype(np.int64), 0, self.g.shape[0] - 1)
        j = np.clip((x / OCC).astype(np.int64), 0, self.g.shape[1] - 1)
        self.g[i, j] |= bit

    def free(self, x, z, r, bits=3):
        i0, i1 = int((z - r) / OCC), int((z + r) / OCC) + 1
        j0, j1 = int((x - r) / OCC), int((x + r) / OCC) + 1
        if i0 < 0 or j0 < 0 or i1 > self.g.shape[0] or j1 > self.g.shape[1]:
            return False
        return not (self.g[i0:i1, j0:j1] & bits).any()


def model_infos(models):
    """template -> its model's box and centre (odol_info), cached; our own MLODs (the SkyBridge,
    the trail signs) aren't autocentred, so their box comes from their points."""
    info = {}

    def model_info(tpl):
        if tpl not in info:
            path = os.path.join("P:\\", models[tpl])
            i = odol_info(path)
            if i is None:
                import mlod
                pts = np.vstack([lod["pts"] for lod in mlod.read(path)["lods"] if len(lod["pts"])])
                i = {"min": tuple(pts.min(0)), "max": tuple(pts.max(0)), "center": (0.0, 0.0, 0.0)}
            info[tpl] = i
        return info[tpl]
    return model_info


OVERHEAD = ("power_wire", "power_wiretel", "cableway_cart")      # wires and lift chairs: nothing on the ground


def mark_objects(occ, tpl, sel, model_info):
    """Mark one template's placed objects (rows x, z, yaw, pitch, roll, scale, rel) on the
    occupancy grid: trees and bushes by their trunk, everything else by its model's box."""
    x, z, yaw, scale = sel[:, 0], sel[:, 1], np.radians(sel[:, 2]), sel[:, 5]
    if tpl.startswith(OVERHEAD):
        return
    if tpl.startswith(("t_", "b_")):
        occ.mark(x, z, 1)
        return
    i = model_info(tpl)
    (x0, _, z0), (x1, _, z1) = i["min"], i["max"]
    lx, lz = np.meshgrid(np.linspace(x0, x1, max(2, int(math.ceil((x1 - x0) / 1.0)) + 1)),
                         np.linspace(z0, z1, max(2, int(math.ceil((z1 - z0) / 1.0)) + 1)))
    lx, lz = lx.ravel(), lz.ravel()
    for s in range(0, len(sel), 20000):
        ca, sa, sc = np.cos(yaw[s:s + 20000])[:, None], np.sin(yaw[s:s + 20000])[:, None], scale[s:s + 20000, None]
        wx = x[s:s + 20000, None] + sc * (lx * ca + lz * sa)
        wz = z[s:s + 20000, None] + sc * (-lx * sa + lz * ca)
        occ.mark(wx.ravel(), wz.ravel(), 2)


class Points:
    """Spatial hash of 2D points for radius and nearest queries."""

    def __init__(self, xz, cell=100.0):
        self.xz = np.asarray(xz, float).reshape(-1, 2)
        self.cell = cell
        self.d = {}
        for i, (x, z) in enumerate(self.xz):
            self.d.setdefault((int(x // cell), int(z // cell)), []).append(i)

    def within(self, x, z, r):
        k = int(math.ceil(r / self.cell))
        ci, cj = int(x // self.cell), int(z // self.cell)
        out = []
        for a in range(ci - k, ci + k + 1):
            for b in range(cj - k, cj + k + 1):
                for i in self.d.get((a, b), ()):
                    if (self.xz[i, 0] - x) ** 2 + (self.xz[i, 1] - z) ** 2 <= r * r:
                        out.append(i)
        return out

    def nearest(self, x, z, rmax=3000.0):
        r = self.cell
        while r <= rmax * 2:
            idx = self.within(x, z, r)
            if idx:
                d = np.hypot(self.xz[idx, 0] - x, self.xz[idx, 1] - z)
                k = int(d.argmin())
                if d[k] <= r:
                    return idx[k], float(d[k])
            r *= 2
        return None, float("inf")


def near_mask(xz, radius, res, n):
    """Boolean n x n raster (res m cells, row 0 south): within radius of any point."""
    grid = np.zeros((n, n), np.float32)
    if len(xz):
        i = np.clip((np.asarray(xz)[:, 1] / res).astype(int), 0, n - 1)
        j = np.clip((np.asarray(xz)[:, 0] / res).astype(int), 0, n - 1)
        grid[i, j] = 1.0
    k = int(math.ceil(radius / res))
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    disc = ((xx * xx + yy * yy) * res * res <= radius * radius).astype(np.float32)
    big = n + 2 * k + 1
    f = np.fft.rfft2(grid, (big, big)) * np.fft.rfft2(disc, (big, big))
    out = np.fft.irfft2(f, (big, big))[k:k + n, k:k + n]
    return out > 0.5


def pick(cands, count, spacing, rng, taken=(), taken_spacing=0.0):
    """Greedy pick in the candidates' order: at least `spacing` apart and `taken_spacing` from `taken`."""
    chosen = []
    grid = Points(np.zeros((0, 2)))
    tgrid = Points(np.array([(c["x"], c["z"]) for c in taken]).reshape(-1, 2), max(taken_spacing, 50.0))
    for c in cands:
        if len(chosen) >= count:
            break
        if grid.within(c["x"], c["z"], spacing):
            continue
        if taken_spacing and tgrid.within(c["x"], c["z"], taken_spacing):
            continue
        chosen.append(c)
        k = len(grid.xz)
        grid.xz = np.vstack([grid.xz, [c["x"], c["z"]]])
        grid.d.setdefault((int(c["x"] // grid.cell), int(c["z"] // grid.cell)), []).append(k)
    return chosen


def spiral_free(occ, ter, x, z, r, max_slope, reach=20.0, bits=3):
    """Nearest clear, flat enough spot to (x, z) within reach."""
    for d in np.arange(0.0, reach + 0.1, 2.0):
        steps = 1 if d == 0 else int(2 * math.pi * d / 2.0)
        for k in range(steps):
            t = 2 * math.pi * k / steps
            px, pz = x + d * math.cos(t), z + d * math.sin(t)
            if occ.free(px, pz, r, bits) and ter.steep(px, pz, r) <= max_slope:
                return px, pz
    return None


def heading(dx, dz):
    return math.degrees(math.atan2(dx, dz)) % 360.0


def kmeans(xz, k, rng, iters=25):
    cent = xz[rng.choice(len(xz), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((xz[:, None, :] - cent[None]) ** 2).sum(-1), 1)
        cent = np.array([xz[lab == i].mean(0) if (lab == i).any() else cent[i] for i in range(k)])
    return lab, cent


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vanilla")
    ap.add_argument("out")
    a = ap.parse_args()
    rng = np.random.default_rng(SEED)
    prng = random.Random(SEED)
    summary = []

    # Copy the vanilla mission.
    os.makedirs(a.out, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(a.vanilla):
        dirnames[:] = [d for d in dirnames if not d.lower().startswith("storage_")]
        rel = os.path.relpath(dirpath, a.vanilla)
        os.makedirs(os.path.join(a.out, rel), exist_ok=True)
        for f in filenames:
            shutil.copy2(os.path.join(dirpath, f), os.path.join(a.out, rel, f))
    print("copied vanilla mission", flush=True)

    ter = Terrain(np.load(os.path.join(SRC, "buildings", "elevation.npy")))
    zones = np.load(os.path.join(SRC, "forest", "zones.npy"))[::-1]          # row 0 south, 8 m cells
    zcell = SIZE / zones.shape[0]

    def zone_at(x, z):
        return int(zones[min(int(z / zcell), zones.shape[0] - 1), min(int(x / zcell), zones.shape[1] - 1)])

    models = find_models(MODEL_FOLDERS)
    model_info = model_infos(models)

    # Occupancy of everything placed, and the objects the mission needs.
    occ = Occupancy()
    codes = {}
    buildings, cluster_sources = [], []
    for rel in OBSTACLE_FILES + DETAIL_FILES + ["roads/tb_trails.txt"]:
        c, rows = read_tb(os.path.join(SRC, rel), codes)
        names = {v: k for k, v in codes.items()}
        if rel != "roads/tb_trails.txt":                          # trails are walked on: only clusters
            for code in np.unique(c):
                mark_objects(occ, names[code], rows[c == code], model_info)
        if rel in BUILDING_FILES:
            for code, r in zip(c, rows):
                buildings.append({"tpl": names[code], "x": r[0], "z": r[1], "yaw": r[2], "pitch": r[3],
                                  "roll": r[4], "scale": r[5], "rel": r[6]})
        if rel in CLUSTER_SOURCES:
            cluster_sources.append((c.copy(), rows[:, [0, 1, 2, 5]].copy(), dict(names)))
        print("occupancy: %s (%d objects)" % (rel, len(rows)), flush=True)

    places = osm_places()
    named = [p for p in places if p["kind"].startswith("place=")]

    # ------------------------------------------------ buildings: proto names, clusters, kinds
    proto = {}
    for n in re.findall(r'<group name="([^"]+)"', open(os.path.join(a.vanilla, "mapgroupproto.xml"),
                                                       encoding="utf-8", errors="replace").read()):
        proto[n.lower()] = n
    for b in buildings:
        b["kind"] = kind_of(b["tpl"])
        b["y"] = ter.h(b["x"], b["z"]) + b["rel"]
        b["proto"] = proto.get("land_" + b["tpl"])
    bxz = np.array([(b["x"], b["z"]) for b in buildings])
    bgrid = Points(bxz, 100.0)
    parent = list(range(len(buildings)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(buildings)):
        for j in bgrid.within(bxz[i, 0], bxz[i, 1], 120.0):
            ri, rj = root(i), root(j)
            if ri != rj:
                parent[ri] = rj
    clusters = {}
    for i in range(len(buildings)):
        clusters.setdefault(root(i), []).append(i)
    for members in clusters.values():
        size = len(members)
        cls = "town" if size >= 150 else ("village" if size >= 8 else "solitude")
        for i in members:
            buildings[i]["cluster"] = cls
            buildings[i]["cluster_id"] = members[0]
            buildings[i]["cluster_size"] = size
    for b in buildings:
        b["density"] = len(bgrid.within(b["x"], b["z"], 150.0))
        b["tier"] = 1 + sum(ter.h(b["x"], b["z"]) >= t for t in TIER_HEIGHTS)

    # ------------------------------------------------ mapgrouppos.xml
    lines = []
    for b in buildings:
        if not b["proto"]:
            continue
        yaw = (b["yaw"] + 180.0) % 360.0 - 180.0
        lines.append('    <group name="%s" pos="%.6f %.6f %.6f" rpy="%.6f %.6f %.6f" a="%.6f" />'
                     % (b["proto"], b["x"], b["y"], b["z"], b["roll"], b["pitch"], yaw, 90.0 - yaw))
    with open(os.path.join(a.out, "mapgrouppos.xml"), "w", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<map>\n' + "\n".join(lines) + "\n</map>\n")
    summary.append("mapgrouppos.xml: %d buildings with loot (of %d placed)" % (len(lines), len(buildings)))
    print(summary[-1], flush=True)

    # ------------------------------------------------ clusters: mapclusterproto.xml, mapgroupcluster*.xml
    proto_text = open(os.path.join(a.vanilla, "mapclusterproto.xml"), encoding="utf-8").read()
    vanilla_shape = {s.lower().replace("/", "\\"): n for n, s in
                     re.findall(r'<export name="([^"]+)" shape="([^"]+)"', proto_text)}
    vanilla_de = dict(re.findall(r'<cluster name="([^"]+)"[^>]*>\s*<de name="([^"]+)"', proto_text))
    new_exports, new_clusters = [], []
    entries, by_de = [], {}
    crng = np.random.default_rng(SEED + 3)       # fruit, berries, stones: their own draws, so mushrooms don't move
    for c, rows, names in cluster_sources:
        for code in np.unique(c):
            tpl = names[code]
            de = next((d for d, pre in CLUSTERS if tpl.startswith(pre)), None)
            if de is None:
                continue
            share = next(s for pre, s in CLUSTER_SHARE if tpl.startswith(pre))
            i = model_info(tpl)
            shape = models[tpl]
            name = vanilla_shape.get(shape.lower())
            if not name or vanilla_de.get(name) != de:
                name = "GSM_" + tpl
                bcx, bcy, bcz = i["center"]
                (x0, y0, z0), (x1, y1, z1) = i["min"], i["max"]
                if "_fallen" in tpl:                                   # points along the log
                    along_x = (x1 - x0) >= (z1 - z0)
                    half = 0.4 * max(x1 - x0, z1 - z0)
                    mx, mz = (x0 + x1) / 2, (z0 + z1) / 2
                    pts = [((mx + t * half, mz + side) if along_x else (mx + side, mz + t * half))
                           for t, side in ((-0.75, 0.7), (-0.25, -0.7), (0.25, 0.7), (0.75, -0.7))]
                    rng_, hgt = 0.6, 1.0
                elif tpl.startswith("b_"):                             # a ring under the bush
                    ring = min(2.0, 0.35 * min(x1 - x0, z1 - z0))
                    pts = [(-bcx + ring * math.cos(math.radians(45 + 90 * k)),
                            -bcz + ring * math.sin(math.radians(45 + 90 * k))) for k in range(4)]
                    rng_, hgt = 0.6, 1.0
                else:                                                  # a ring round the trunk
                    ring = 0.9 if "_stump" in tpl else 1.8
                    pts = [(-bcx + ring * math.cos(math.radians(45 + 90 * k)),
                            -bcz + ring * math.sin(math.radians(45 + 90 * k))) for k in range(4)]
                    rng_, hgt = (0.5, 1.0) if "_stump" in tpl else (0.8, 2.0)
                new_exports.append('\t\t\t<export name="%s" shape="%s" />' % (name, shape))
                new_clusters.append(
                    '\t\t<cluster name="%s" lootmax="2" maxinstances="150">\n\t\t\t<de name="%s" />\n'
                    '\t\t\t<container name="branch" lootmax="1">\n%s\t\t\t</container>\n\t\t</cluster>'
                    % (name, de, "".join('\t\t\t<point pos="%.2f %.2f %.2f" range="%.2f" height="%.2f" flags="32" />\n'
                                         % (px, -bcy + 0.35, pz, rng_, hgt) for px, pz in pts)))
            sel = rows[c == code]
            keep = (rng if de in MUSHROOM_EVENTS else crng).random(len(sel)) < share
            by_de[de] = by_de.get(de, 0) + int(keep.sum())
            bcy = i["center"][1]
            for x, z, yaw, scale in sel[keep]:
                yaw = (yaw + 180.0) % 360.0 - 180.0
                entries.append('    <group name="%s" pos="%.6f %.6f %.6f" a="%.6f" />'
                               % (name, x, ter.h(x, z) + bcy, z, 90.0 - yaw))
    proto_text = proto_text.replace("\t\t</clusters>", "\n".join(new_exports) + "\n\t\t</clusters>", 1)
    k = proto_text.rfind("</prototype>")
    proto_text = proto_text[:k] + "<!--Great Smoky Mountains: this map's trees, dead wood and bushes -->\n" + \
        "\n".join(new_clusters) + "\n" + proto_text[k:]
    with open(os.path.join(a.out, "mapclusterproto.xml"), "w", newline="\n", encoding="utf-8") as fh:
        fh.write(proto_text)
    # At most CLUSTERS_PER_FILE spots a file, as vanilla splits them: one file of 288,517 corrupted
    # the server's memory as it loaded. The economy reads mapgroupcluster.xml, and each file names
    # the next with <include file="mapgroupcluster01" /> and so on.
    if len(entries) > CLUSTERS_PER_FILE * CLUSTER_FILES:
        entries = [entries[k] for k in np.linspace(0, len(entries) - 1, CLUSTERS_PER_FILE * CLUSTER_FILES).astype(int)]
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<map>\n'
    used = max(1, -(-len(entries) // CLUSTERS_PER_FILE))
    for n in range(CLUSTER_FILES):            # also empties vanilla's files, which hold Chernarus trees
        part = entries[n * CLUSTERS_PER_FILE:(n + 1) * CLUSTERS_PER_FILE]
        name = "mapgroupcluster.xml" if n == 0 else "mapgroupcluster%02d.xml" % n
        link = '    <include file="mapgroupcluster%02d" />\n' % (n + 1) if n + 1 < used else ""
        with open(os.path.join(a.out, name), "w", newline="\n") as fh:
            fh.write(head + "".join(e + "\n" for e in part) + link + "</map>\n")
    summary.append("mapgroupcluster*.xml: %d cluster spots in %d files (%s); %d new cluster types"
                   % (len(entries), -(-len(entries) // CLUSTERS_PER_FILE),
                      ", ".join("%s %d" % kv for kv in sorted(by_de.items())), len(new_clusters)))
    print(summary[-1], flush=True)
    del cluster_sources

    # ------------------------------------------------ roads
    road_lines = json.load(open(os.path.join(SRC, "roads", "lines.json")))
    road_pts, road_cands, trail_pts = [], [], []
    for ln in road_lines:
        pts = np.array(ln["points"])
        seg = np.diff(pts, axis=0)
        segl = np.hypot(seg[:, 0], seg[:, 1])
        cum = np.concatenate([[0], np.cumsum(segl)])
        step = 10.0
        for d in np.arange(0.0, cum[-1], step):
            k = min(int(np.searchsorted(cum, d, "right") - 1), len(seg) - 1)
            if segl[k] == 0:
                continue
            t = (d - cum[k]) / segl[k]
            x, z = pts[k] + t * seg[k]
            dx, dz = seg[k] / segl[k]
            if ln["group"] == "trails":
                trail_pts.append((x, z))
                continue
            road_pts.append((x, z))
            if int(d) % 20 == 0 and not ln.get("bridge"):
                road_cands.append({"x": x, "z": z, "dx": dx, "dz": dz, "family": ln["family"],
                                   "highway": ln["highway"], "name": ln.get("name", "")})
    road_pts, trail_pts = np.array(road_pts), np.array(trail_pts)
    roadgrid = Points(road_pts, 50.0)

    def building_near(x, z, r):
        return [buildings[i] for i in bgrid.within(x, z, r)]

    def describe(c):
        i, d = bgrid.nearest(c["x"], c["z"], 1500.0)
        c["bdist"] = d
        c["bcluster"] = buildings[i]["cluster"] if i is not None and d < 150 else "wild"
        return c

    # ------------------------------------------------ vehicles
    veh_cands = []
    for c in road_cands:
        hw = ROAD_HALF_WIDTH.get(c["family"])
        if hw is None:
            continue
        off = hw - 1.4
        x, z = c["x"] + c["dz"] * off, c["z"] - c["dx"] * off            # right-hand side of the road
        if not occ.free(x, z, 2.6) or ter.steep(x, z, 4.0) > 0.14:
            continue
        veh_cands.append(describe({"x": x, "z": z, "a": heading(c["dx"], c["dz"]), "src": "road",
                                   "highway": c["highway"], "family": c["family"]}))
    lots = [p for p in places if p["kind"] in ("amenity=parking", "highway=trailhead", "tourism=camp_site",
                                                "amenity=ranger_station", "tourism=picnic_site",
                                                "tourism=viewpoint", "tourism=information")]
    for p in lots:
        spot = spiral_free(occ, ter, p["x"], p["z"], 3.0, 0.1, 25.0)
        if not spot:
            continue
        i, _ = roadgrid.nearest(spot[0], spot[1], 400.0)
        a_ = prng.uniform(0, 360)
        if i is not None and i + 1 < len(road_pts):
            d = road_pts[i + 1] - road_pts[i]
            if np.hypot(*d) > 0:
                a_ = heading(d[0], d[1])
        veh_cands.append(describe({"x": spot[0], "z": spot[1], "a": a_, "src": p["kind"], "highway": "",
                                   "family": ""}))
    prng.shuffle(veh_cands)
    print("vehicle spots: %d candidates" % len(veh_cands), flush=True)

    def by(pred, prefer=lambda c: 0):
        return sorted([c for c in veh_cands if pred(c)], key=prefer)

    remote = ("highway=trailhead", "tourism=camp_site", "amenity=ranger_station", "tourism=picnic_site",
              "tourism=viewpoint")
    town_car = lambda c: c["bcluster"] in ("town", "village") or (c["src"] == "amenity=parking" and c["bdist"] < 300)
    vehicle_plan = [
        ("VehicleCivilianSedan", 45, town_car, lambda c: c["src"] == "road"),
        ("VehicleSedan02", 45, town_car, lambda c: c["src"] == "road"),
        ("VehicleHatchback02", 45, town_car, lambda c: c["src"] == "road"),
        ("VehicleOffroadHatchback", 60, lambda c: c["bdist"] > 250 or c["src"] in remote,
         lambda c: c["src"] not in remote),
        ("VehicleOffroad02", 20, lambda c: c["src"] in remote or c["highway"] in ("track", "unclassified"),
         lambda c: c["src"] != "amenity=ranger_station"),
        ("VehicleTruck01", 50, lambda c: c["highway"] in ("trunk", "primary", "secondary") or any(
            b["kind"] in ("industrial", "farm") for b in building_near(c["x"], c["z"], 80.0)),
         lambda c: c["bdist"] > 150),
        ("VehicleMotorbike", 50, lambda c: True, lambda c: 0),
    ]
    events = {}
    taken = []
    for ev, n, pred, prefer in vehicle_plan:
        got = pick(by(pred, prefer), n, 250.0, rng, taken, 90.0)
        taken += got
        events[ev] = ['<pos x="%.6f" z="%.6f" a="%.6f" />' % (c["x"], c["z"], c["a"]) for c in got]
        summary.append("%s: %d spots" % (ev, len(got)))
        print(summary[-1], flush=True)

    # Police car wrecks: in the middle of the road, slewed a little.
    pol = []
    for c in road_cands:
        if c["family"] not in ROAD_HALF_WIDTH or not occ.free(c["x"], c["z"], 2.6) or ter.steep(c["x"], c["z"], 4) > 0.15:
            continue
        cc = describe({"x": c["x"], "z": c["z"], "a": (heading(c["dx"], c["dz"]) + prng.uniform(-25, 25)) % 360})
        if cc["bcluster"] in ("town", "village") or c["highway"] in ("trunk", "primary"):
            pol.append(cc)
    prng.shuffle(pol)
    got = pick(pol, 60, 300.0, rng, taken, 60.0)
    events["StaticPoliceCar"] = ['<pos x="%.6f" z="%.6f" a="%.6f" />' % (c["x"], c["z"], c["a"]) for c in got]
    summary.append("StaticPoliceCar: %d spots" % len(got))

    # ------------------------------------------------ wilderness spots: heli crashes, supply crates, Santa
    n20 = int(SIZE / 20)
    near_bld = near_mask(bxz, 700.0, 20.0, n20)
    near_road = near_mask(road_pts, 40.0, 20.0, n20)
    wild = []
    for gz in np.arange(60.0, SIZE - 60, 50.0):
        for gx in np.arange(60.0, SIZE - 60, 50.0):
            x, z = gx + prng.uniform(-20, 20), gz + prng.uniform(-20, 20)
            if near_bld[int(z / 20), int(x / 20)] or near_road[int(z / 20), int(x / 20)]:
                continue
            if ter.steep(x, z, 10.0) > 0.2:
                continue
            if not occ.free(x, z, 12.0, 2) or not occ.free(x, z, 6.0, 1):
                continue
            wild.append({"x": x, "z": z, "open": zone_at(x, z) == 0, "h": ter.h(x, z)})
    prng.shuffle(wild)
    # A weighted shuffle: meadows and balds, and the higher tiers, come first (their own random
    # numbers, so the picks after these don't move).
    wrng = random.Random(SEED + 1)
    for c in wild:
        w = WILD_TIER_WEIGHT[1 + sum(c["h"] >= t for t in TIER_HEIGHTS)] * (2.0 if c["open"] else 1.0)
        c["key"] = wrng.random() ** (1.0 / w)
    wild.sort(key=lambda c: -c["key"])
    print("wilderness spots: %d" % len(wild), flush=True)
    heli = pick(wild, 40, 1100.0, rng)
    events["StaticHeliCrash"] = ['<pos x="%.6f" z="%.6f" a="-1" />' % (c["x"], c["z"]) for c in heli]
    crates = pick(wild, 24, 1100.0, rng, heli, 500.0)
    events["StaticAirplaneCrate"] = ['<pos x="%.6f" z="%.6f" />' % (c["x"], c["z"]) for c in crates]
    santa = pick(wild, 15, 1500.0, rng, heli + crates, 400.0)
    events["StaticSantaCrash"] = ['<pos x="%.2f" z="%.2f" a="0" y="%.2f"/>' % (c["x"], c["z"], c["h"]) for c in santa]
    tiers_of = lambda spots: "/".join(str(sum(1 + sum(c["h"] >= t for t in TIER_HEIGHTS) == k for c in spots))
                                      for k in (1, 2, 3, 4))
    summary.append("StaticHeliCrash: %d spots (%d in meadows or balds; tiers 1-4 %s); StaticAirplaneCrate %d (%s); "
                   "StaticSantaCrash %d" % (len(heli), sum(c["open"] for c in heli), tiers_of(heli), len(crates),
                                            tiers_of(crates), len(santa)))
    print(summary[-1], flush=True)

    # Bonfires: campsites, shelters, picnic sites, viewpoints, and beside trails.
    fires = []
    for p in places:
        if p["kind"] in ("tourism=camp_site", "amenity=shelter", "tourism=picnic_site", "tourism=viewpoint",
                         "tourism=alpine_hut", "highway=trailhead"):
            spot = spiral_free(occ, ter, p["x"], p["z"], 2.0, 0.2, 30.0)
            if spot:
                fires.append({"x": spot[0], "z": spot[1]})
    for x, z in trail_pts[rng.permutation(len(trail_pts))[:3000]]:
        t = prng.uniform(0, 2 * math.pi)
        px, pz = x + 10 * math.cos(t), z + 10 * math.sin(t)
        if occ.free(px, pz, 2.0) and ter.steep(px, pz, 3) < 0.2 and not near_bld[int(pz / 20), int(px / 20)]:
            fires.append({"x": px, "z": pz})
    got = pick(fires, 63, 400.0, rng)
    events["StaticBonfire"] = ['<pos x="%.6f" z="%.6f" />' % (c["x"], c["z"]) for c in got]
    summary.append("StaticBonfire: %d spots" % len(got))

    # Plank piles beside sheds, barns and some cabins.
    planks = []
    for b in buildings:
        if b["kind"] not in ("shed", "farm", "industrial") and prng.random() > 0.25:
            continue
        i = model_info(b["tpl"])
        (x0, _, z0), (x1, _, z1) = i["min"], i["max"]
        for lx, lz in prng.sample([(x1 + 2.5, 0.0), (x0 - 2.5, 0.0), (0.0, z1 + 2.5), (0.0, z0 - 2.5)], 4):
            t = math.radians(b["yaw"])
            px = b["x"] + lx * math.cos(t) + lz * math.sin(t)
            pz = b["z"] - lx * math.sin(t) + lz * math.cos(t)
            if occ.free(px, pz, 1.6) and ter.steep(px, pz, 2) < 0.3:
                planks.append({"x": px, "z": pz, "a": b["yaw"] % 360})
                break
    prng.shuffle(planks)
    got = pick(planks, 295, 60.0, rng)
    events["ItemPlanks"] = ['<pos x="%.6f" z="%.6f" a="%.6f" />' % (c["x"], c["z"], c["a"]) for c in got]
    summary.append("ItemPlanks: %d spots" % len(got))

    # Christmas trees: open spots in the towns.
    xmas = []
    for b in sorted(buildings, key=lambda b: -b["density"]):
        if b["cluster"] == "solitude":
            continue
        spot = spiral_free(occ, ter, b["x"], b["z"], 4.0, 0.1, 40.0)
        if spot:
            xmas.append({"x": spot[0], "z": spot[1]})
        if len(xmas) > 400:
            break
    got = pick(xmas, 13, 900.0, rng)
    events["StaticChristmasTree"] = ['<pos x="%.2f" z="%.2f" a="0.0" />' % (c["x"], c["z"]) for c in got]

    # ------------------------------------------------ convoys and police scenes: cfgeventgroups.xml
    # Laid out on this map's own roads (vanilla's groups fit Chernarus's), with their own random
    # numbers. Everything stands in the right-hand lane or on the shoulder, so one lane stays open:
    # Newfound Gap Road is the only way over the mountains.
    grng = random.Random(SEED + 2)
    tier_at = lambda x, z: 1 + sum(ter.h(x, z) >= t for t in TIER_HEIGHTS)
    glines = []
    for ln in road_lines:
        if ln["group"] == "trails" or ln["family"] not in ROAD_HALF_WIDTH or ln.get("bridge") or ln["highway"] == "track":
            continue
        pts = np.array(ln["points"])
        segl = np.hypot(*np.diff(pts, axis=0).T)
        if segl.sum() > 120.0:
            glines.append((pts, np.concatenate([[0], np.cumsum(segl)]), ln))

    def along(li, s):
        pts, cum, _ = glines[li]
        s = min(max(s, 0.0), cum[-1] - 1e-3)
        k = min(int(np.searchsorted(cum, s, "right") - 1), len(pts) - 2)
        d = pts[k + 1] - pts[k]
        n = np.hypot(*d)
        if n == 0:
            return None
        t = (s - cum[k]) / n
        return pts[k][0] + t * d[0], pts[k][1] + t * d[1], d[0] / n, d[1] / n

    def put(c, ds, lat, turn, kind, r, loot=None):
        """A child ds metres along the road from the spot, lat metres right of its centre line, or
        further right if it would leave less than OPEN_LANE of the road beside it."""
        p = along(c["li"], c["s"] + ds)
        if p is None:
            return None
        w, ln = next(v for k, v in WRECK_SIZE.items() if k in kind)
        t = math.radians(turn)
        lat = max(lat, -ROAD_HALF_WIDTH[c["family"]] + OPEN_LANE + w / 2 * abs(math.cos(t)) + ln / 2 * abs(math.sin(t)))
        x, z = p[0] + p[3] * lat, p[1] - p[2] * lat
        if not occ.free(x, z, r) or ter.steep(x, z, 3.0) > 0.2:
            return None
        return {"type": kind, "x": x, "z": z, "a": (heading(p[2], p[3]) + turn) % 360, "loot": loot}

    def convoy(c, ambush):
        lane = ROAD_HALF_WIDTH[c["family"]] / 2
        n, sp = grng.randint(3, 5), grng.uniform(13.0, 16.0)
        kids = []
        for k in range(n):
            kind = "StaticObj_Wreck_T72_Chassis_DE" if ambush and k == 0 else grng.choice(CONVOY_WRECKS)
            ch = put(c, (k - (n - 1) / 2) * sp, lane + grng.uniform(-0.3, 0.3),
                     grng.uniform(-25, 25) if ambush else grng.uniform(-6, 6), kind, 2.0, (2, 4 if "T72" in kind else 3))
            if ch:
                kids.append(ch)
                if grng.random() < 0.5:
                    kids.append(dict(ch, type="StaticObj_Wreck_Decal_Small2_DE", loot=None))
        if ambush and kids and "T72" in kids[0]["type"]:          # its turret, blown off beside the road
            t = put(c, -(n - 1) / 2 * sp, ROAD_HALF_WIDTH[c["family"]] + 3.0, grng.uniform(0, 360),
                    "StaticObj_Wreck_T72_Turret_DE", 2.5)
            if t:
                kids.append(dict(t, y=0.6))
        return kids if sum(1 for k in kids if k["loot"]) >= 3 else None

    def road_scene(c):
        lane = ROAD_HALF_WIDTH[c["family"]] / 2
        if grng.random() < 0.5:                                      # a roadblock across the right lane
            kids = [put(c, 0.0, lane + 0.8, grng.uniform(20, 40), grng.choice(POLICE_WRECKS), 1.6, (2, 4)),
                    put(c, -9.0, lane, 0.0, "StaticObj_Roadblock_Wood_Long_DE", 1.0),
                    put(c, 9.0, lane, 0.0, "StaticObj_Roadblock_Wood_Long_DE", 1.0),
                    put(c, 16.0, lane, grng.uniform(-10, 10), grng.choice(CIVIL_WRECKS), 2.0, (1, 2))]
            kind = "block"
        else:                                                        # a crash, and the police who came to it
            kids = [put(c, 0.0, lane, grng.uniform(15, 50), grng.choice(CIVIL_WRECKS), 2.0, (1, 2)),
                    put(c, 6.5, lane + 0.4, grng.uniform(-50, -15), grng.choice(CIVIL_WRECKS), 2.0, (1, 2)),
                    put(c, -12.0, lane + 0.5, grng.uniform(-15, 15), grng.choice(POLICE_WRECKS), 1.6, (2, 4))]
            kids += [dict(k, type="StaticObj_Wreck_Decal_Small1_DE", loot=None) for k in kids[:2] if k]
            kind = "crash"
        kids = [k for k in kids if k]
        return (kids, kind) if sum(1 for k in kids if k["loot"]) >= 2 else (None, kind)

    def lot_scene(c):
        """Abandoned cars in a trailhead or overlook car park, and a ranger's car, all off the road."""
        kids, spots = [], []
        for kind in [grng.choice(CIVIL_WRECKS) for _ in range(grng.randint(3, 4))] + [grng.choice(POLICE_WRECKS[2:])]:
            for _ in range(12):
                t, d = grng.uniform(0, 2 * math.pi), grng.uniform(0, 22)
                x, z = c["x"] + d * math.cos(t), c["z"] + d * math.sin(t)
                if all(math.hypot(x - u, z - v) > 6.5 for u, v in spots) and occ.free(x, z, 2.0) and \
                        ter.steep(x, z, 3.0) < 0.12 and not roadgrid.within(x, z, 8.0):
                    spots.append((x, z))
                    kids.append({"type": kind, "x": x, "z": z, "a": grng.uniform(0, 360),
                                 "loot": (2, 4) if kind in POLICE_WRECKS else (1, 2)})
                    break
        return kids if len(kids) >= 3 else None

    road_spots = []
    for li, (pts, cum, ln) in enumerate(glines):
        for s in np.arange(40.0, cum[-1] - 40.0, 30.0):
            p = along(li, s)
            if p:
                road_spots.append({"li": li, "s": s, "x": p[0], "z": p[1], "family": ln["family"],
                                   "highway": ln["highway"], "name": ln.get("name", ""), "tier": tier_at(p[0], p[1])})
    grng.shuffle(road_spots)
    lot_spots = [{"x": p["x"], "z": p["z"], "tier": tier_at(p["x"], p["z"]), "name": p["name"]}
                 for p in places if p["kind"] in SCENE_PLACES]
    grng.shuffle(lot_spots)
    big_road = lambda c: c["highway"] in ("trunk", "trunk_link", "primary", "primary_link", "secondary") or \
        c["name"] in ("Kuwohi Access Road", "Roaring Fork Motor Nature Trail")
    scenes, placed = [], []

    def far(c, ev, spacing):
        """spacing from the same event's spots, 400 m from the other's, 60 m from vehicle spawns."""
        return all(math.hypot(c["x"] - x, c["z"] - z) > (spacing if e == ev else 400.0) for x, z, e in placed) and \
            all(math.hypot(c["x"] - t["x"], c["z"] - t["z"]) > 60.0 for t in taken)
    for t in (1, 2, 3, 4):
        n = 0
        for c in road_spots:
            if n >= CONVOYS[t] or c["tier"] != t or not big_road(c) or not far(c, "StaticMilitaryConvoy", 1000.0):
                continue
            kids = convoy(c, ambush=n % 2 == 0)              # every other one led by a tank: explosives
            if kids:
                scenes.append(("StaticMilitaryConvoy", "GSM_Convoy_%d_%02d" % (t, n + 1), kids, "convoy"))
                placed.append((c["x"], c["z"], "StaticMilitaryConvoy"))
                n += 1
    for t in (1, 2, 3, 4):
        n = 0
        lots = [c for c in lot_spots if c["tier"] == t]
        roads = [c for c in road_spots if c["tier"] == t]
        for c in [x for pair in zip(lots, roads) for x in pair] + lots[len(roads):] + roads[len(lots):]:
            if n >= SITUATIONS[t] or not far(c, "StaticPoliceSituation", 700.0):
                continue
            kids, kind = (lot_scene(c), "lot") if "li" not in c else road_scene(c)
            if kids:
                scenes.append(("StaticPoliceSituation", "GSM_Scene_%d_%02d" % (t, n + 1), kids, kind))
                placed.append((c["x"], c["z"], "StaticPoliceSituation"))
                n += 1
    gx = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', "<eventgroupdef>"]
    for ev, name, kids, kind in scenes:
        kids.sort(key=lambda k: not k["loot"])               # a lootable wreck at the group's origin
        ox, oz = kids[0]["x"], kids[0]["z"]
        events.setdefault(ev, []).append('<pos x="%.3f" z="%.3f" a="0" y="%.3f" group="%s"/>'
                                         % (ox, oz, ter.h(ox, oz), name))
        gx.append('    <group name="%s">' % name)
        for k in kids:
            more = (' deloot="1" lootmax="%d" lootmin="%d"' % (k["loot"][1], k["loot"][0]) if k["loot"]
                    else ' spawnsecondary="false"')
            gx.append('        <child type="%s"%s x="%.3f" z="%.3f" a="%.3f"%s/>'
                      % (k["type"], more, k["x"] - ox, k["z"] - oz, k["a"], ' y="%.1f"' % k["y"] if "y" in k else ""))
        gx.append("    </group>")
    gx.append("</eventgroupdef>")
    with open(os.path.join(a.out, "cfgeventgroups.xml"), "w", newline="\n") as fh:
        fh.write("\n".join(gx) + "\n")
    count = lambda ev, t: sum(1 for g in scenes if g[0] == ev and g[1].split("_")[2] == str(t))
    summary.append("StaticMilitaryConvoy: %d spots (tiers 1-4 %s); StaticPoliceSituation: %d (%s; %d roadblocks, "
                   "%d crashes, %d car parks)"
                   % (sum(1 for g in scenes if g[0] == "StaticMilitaryConvoy"),
                      "/".join(str(count("StaticMilitaryConvoy", t)) for t in (1, 2, 3, 4)),
                      sum(1 for g in scenes if g[0] == "StaticPoliceSituation"),
                      "/".join(str(count("StaticPoliceSituation", t)) for t in (1, 2, 3, 4)),
                      sum(1 for g in scenes if g[3] == "block"), sum(1 for g in scenes if g[3] == "crash"),
                      sum(1 for g in scenes if g[3] == "lot")))
    print(summary[-1], flush=True)

    # ------------------------------------------------ cfgeventspawns.xml
    van = open(os.path.join(a.vanilla, "cfgeventspawns.xml"), encoding="utf-8").read()
    order = re.findall(r'<event name="([^"]+)"', van)
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', "<eventposdef>"]
    for ev in order:
        pos = events.get(ev)
        if not pos:
            out.append('\t<event name="%s" />' % ev)
            continue
        out.append('\t<event name="%s">' % ev)
        if ev in ZONE:
            out.append("\t\t" + ZONE[ev])
        out += ["\t\t" + p for p in pos]
        out.append("\t</event>")
    out.append("</eventposdef>")
    with open(os.path.join(a.out, "cfgeventspawns.xml"), "w", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")

    # ------------------------------------------------ db/events.xml: switch off what can't spawn here
    evx = open(os.path.join(a.out, "db", "events.xml"), encoding="utf-8").read()
    for ev in SWITCH_OFF:
        evx = re.sub(r'(<event name="%s">.*?<active>)1(</active>)' % ev, r"\g<1>0\2", evx, count=1, flags=re.S)
    evx = re.sub(r'(<event name="StaticHeliCrash">.*?<nominal>)\d+(</nominal>)', r"\g<1>%d\2" % HELI_CRASHES_AT_ONCE,
                 evx, count=1, flags=re.S)
    for ev in BERRY_EVENTS:
        evx = re.sub(r'(<event name="%s">.*?<active>)0(</active>)' % ev, r"\g<1>1\2", evx, count=1, flags=re.S)
    for ev in re.findall(r'<event name="(Trajectory\w+)">', evx):
        evx = re.sub(r'(<event name="%s">.*?<nominal>)\d+(</nominal>)' % ev,
                     r"\g<1>%d\2" % TRAJECTORY_NOMINAL.get(ev, TRAJECTORY_NOMINAL_DEFAULT), evx, count=1, flags=re.S)
    # Black bears are what the Smokies are known for: a few more of them about.
    evx = re.sub(r'(<event name="AnimalBear">.*?<min>)\d+(</min>\s*<max>)\d+(</max>)', r"\g<1>3\g<2>5\3", evx,
                 count=1, flags=re.S)
    with open(os.path.join(a.out, "db", "events.xml"), "w", newline="\n", encoding="utf-8") as fh:
        fh.write(evx)
    summary.append("db/events.xml: switched off %s; switched on %s; StaticHeliCrash %d at a time; Trajectory "
                   "events %d at a time (stones %d); AnimalBear min 3 max 5"
                   % (", ".join(SWITCH_OFF), ", ".join(BERRY_EVENTS), HELI_CRASHES_AT_ONCE, TRAJECTORY_NOMINAL_DEFAULT,
                      TRAJECTORY_NOMINAL["TrajectoryStones"]))

    # ------------------------------------------------ player spawns
    groups = []
    town = [i for i, b in enumerate(buildings) if b["cluster"] == "town"]
    if town:
        txz = bxz[town]
        lab, cent = kmeans(txz, min(8, max(1, len(town) // 120)), rng)
        for k, (cx, cz) in enumerate(cent):
            members = [town[i] for i in np.nonzero(lab == k)[0]]
            groups.append((members, cx, cz))
    for cid, members in clusters.items():
        if 20 <= len(members) < 150:
            m = np.array(members)
            groups.append((list(m), float(bxz[m, 0].mean()), float(bxz[m, 1].mean())))
    spawn_groups, used = [], {}
    for members, cx, cz in groups:
        p = min(named, key=lambda p: (p["x"] - cx) ** 2 + (p["z"] - cz) ** 2)
        name = p["name"].replace(" ", "")
        if math.hypot(p["x"] - cx, p["z"] - cz) > 500:          # e.g. Gatlinburg_NE
            name += "_" + ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((heading(cx - p["x"], cz - p["z"]) + 22.5)
                                                                             % 360) // 45)]
        used[name] = used.get(name, 0) + 1
        label = name if used[name] == 1 else "%s_%d" % (name, used[name])
        pts = []
        for _ in range(400):
            b = buildings[members[prng.randrange(len(members))]]
            t, d = prng.uniform(0, 2 * math.pi), prng.uniform(15, 60)
            x, z = b["x"] + d * math.cos(t), b["z"] + d * math.sin(t)
            if occ.free(x, z, 3.0) and ter.steep(x, z, 3) < 0.3:
                pts.append({"x": x, "z": z})
        pts = pick(pts, 5, 60.0, rng)
        if pts:
            h = np.mean([ter.h(p["x"], p["z"]) for p in pts])
            spawn_groups.append({"name": label, "pts": pts, "h": h, "size": len(members)})
    spawn_groups = sorted([g for g in spawn_groups if g["h"] < TIER_HEIGHTS[1]], key=lambda g: g["h"])  # not LeConte
    fresh = [g for g in spawn_groups if g["h"] < TIER_HEIGHTS[0]] or spawn_groups[:6]
    pv = open(os.path.join(a.vanilla, "cfgplayerspawnpoints.xml"), encoding="utf-8").read()

    def bubbles(gs):
        s = "        <generator_posbubbles>\n"
        for g in gs:
            s += '            <group name="%s">\n' % g["name"]
            s += "".join('                <pos x="%.6f" z="%.6f" />\n' % (p["x"], p["z"]) for p in g["pts"])
            s += "            </group>\n"
        return s + "        </generator_posbubbles>"
    for section, gs in (("fresh", fresh), ("hop", spawn_groups), ("travel", spawn_groups)):
        pv = re.sub(r"(<%s>.*?)<generator_posbubbles>.*?</generator_posbubbles>" % section,
                    lambda m: m.group(1) + bubbles(gs).lstrip(), pv, count=1, flags=re.S)
    with open(os.path.join(a.out, "cfgplayerspawnpoints.xml"), "w", newline="\n", encoding="utf-8") as fh:
        fh.write(pv)
    summary.append("player spawns: fresh %d areas (%s), hop and travel %d areas"
                   % (len(fresh), ", ".join(g["name"] for g in fresh), len(spawn_groups)))
    print(summary[-1], flush=True)

    # Contaminated areas: none; safe positions are the fresh spawns.
    eff = json.load(open(os.path.join(a.vanilla, "cfgeffectarea.json")))
    eff["Areas"] = []
    eff["SafePositions"] = [[round(p["x"]), round(p["z"])] for g in fresh for p in g["pts"]]
    with open(os.path.join(a.out, "cfgeffectarea.json"), "w", newline="\n") as fh:
        json.dump(eff, fh, indent=4)

    # Climate: Gatlinburg's monthly normals, as sea-level base temperatures.
    path = os.path.join(a.out, "cfggameplay.json")
    text = open(path, encoding="utf-8", newline="").read()
    for key, temps in (("environmentMinTemps", CLIMATE_MIN), ("environmentMaxTemps", CLIMATE_MAX)):
        base = ", ".join("%.1f" % (t + CLIMATE_OFFSET) for t in temps)
        text, n = re.subn(r'"%s":\s*\[[^\]]*\]' % key, '"%s": [%s]' % (key, base), text, count=1)
        assert n == 1, key
    open(path, "w", encoding="utf-8", newline="").write(text)
    summary.append("climate: Gatlinburg normals + %.1f C (base temperatures; the game takes 1.2 C per 100 m off)"
                   % CLIMATE_OFFSET)

    # ------------------------------------------------ infected
    zcolor = {}
    zt = open(os.path.join(a.vanilla, "env", "zombie_territories.xml")).read()
    for color, body in re.findall(r'<territory color="(\d+)">(.*?)</territory>', zt, re.S):
        for n in set(re.findall(r'name="([^"]+)"', body)):
            zcolor.setdefault(n, color)
    zpts = {}

    def zadd(name, x, z):
        zpts.setdefault(name, []).append((x, z))
    special = {"police": "InfectedPolice", "fire": "InfectedFirefighter", "medic": "InfectedMedic",
               "church": "InfectedReligious", "industrial": "InfectedIndustrial"}
    core = np.percentile([b["density"] for b in buildings if b["cluster"] == "town"] or [0], 70)
    for b in buildings:
        if b["kind"] in special:
            zadd(special[b["kind"]], b["x"], b["z"])
        elif b["cluster"] == "town":                           # the densest 30% is downtown
            zadd("InfectedCity" if b["density"] >= core else "InfectedCityTier1", b["x"], b["z"])
        elif b["cluster"] == "village":
            zadd("InfectedVillageTier1" if b["tier"] == 1 else "InfectedVillage", b["x"], b["z"])
        else:
            zadd("InfectedSolitude", b["x"], b["z"])
    for p in places:
        if p["kind"] in ("tourism=camp_site", "amenity=shelter", "highway=trailhead", "tourism=alpine_hut",
                         "amenity=ranger_station", "tourism=viewpoint", "tourism=picnic_site"):
            zadd("InfectedSolitude", p["x"], p["z"])
        elif p["kind"] in ("historic=ruins", "historic=memorial", "historic=farm", "historic=house"):
            zadd("InfectedSpooky", p["x"], p["z"])
    # One zone per 150 m square of town (200 m village, 400 m in the wild); how many infected
    # by how many buildings it covers, in vanilla's ranges for each kind.
    def infected_count(name, n):
        table = {"InfectedCity": [(10, (8, 12)), (4, (4, 6)), (0, (3, 5))],
                 "InfectedCityTier1": [(10, (5, 8)), (4, (4, 6)), (0, (3, 5))],
                 "InfectedVillage": [(8, (8, 12)), (4, (4, 6)), (0, (3, 5))],
                 "InfectedVillageTier1": [(8, (8, 12)), (4, (4, 6)), (0, (3, 5))],
                 "InfectedSolitude": [(4, (2, 4)), (0, (1, 4))],
                 "InfectedIndustrial": [(3, (4, 8)), (0, (2, 5))],
                 "InfectedReligious": [(0, (1, 3))],
                 "InfectedSpooky": [(0, (4, 8))]}
        return next(c for lo, c in table.get(name, [(0, (3, 5))]) if n >= lo)
    zlines = ['<?xml version="1.0" encoding="UTF-8"?>', "<territory-type>"]
    nz = {}
    for name, pts in sorted(zpts.items()):
        pts = np.array(pts)
        size = {"InfectedSolitude": 400.0, "InfectedSpooky": 400.0, "InfectedVillage": 200.0,
                "InfectedVillageTier1": 200.0}.get(name, 150.0)
        cells = {}
        for key, p in zip(map(tuple, np.floor(pts / size).astype(int)), pts):
            cells.setdefault(key, []).append(p)
        zlines.append('    <territory color="%s">' % zcolor.get(name, "4291611852"))
        for key in sorted(cells):
            g = np.array(cells[key])
            cx, cz = g.mean(0)
            r = float(np.clip(np.hypot(g[:, 0] - cx, g[:, 1] - cz).max() + 30, 50, 120))
            dmin, dmax = infected_count(name, len(g))
            zlines.append('        <zone name="%s" smin="0" smax="0" dmin="%d" dmax="%d" x="%.1f" z="%.1f" r="%.0f"/>'
                          % (name, dmin, dmax, cx, cz, r))
        nz[name] = len(cells)
        zlines.append("    </territory>")
    zlines.append("</territory-type>")
    with open(os.path.join(a.out, "env", "zombie_territories.xml"), "w", newline="\n") as fh:
        fh.write("\n".join(zlines) + "\n")
    summary.append("infected: %d zones (%s)" % (sum(nz.values()), ", ".join("%s %d" % kv for kv in sorted(nz.items()))))
    print(summary[-1], flush=True)

    # ------------------------------------------------ animals
    water_lines = json.load(open(os.path.join(SRC, "water", "lines.json")))
    wpts = []
    for ln in water_lines:
        for x, z in ln["points"][::3]:
            if 0 < x < SIZE and 0 < z < SIZE:
                wpts.append((x, z))
    wgrid = Points(np.array(wpts), 100.0)
    town_mask = near_mask(bxz[[i for i, b in enumerate(buildings) if b["cluster"] == "town"]], 900.0, 20.0, n20)
    bld_mask = near_mask(bxz, 350.0, 20.0, n20)
    farm_xz = [(b["x"], b["z"]) for b in buildings if b["kind"] == "farm" or b["cluster"] == "village"]
    farm_xz += [(p["x"], p["z"]) for p in places if p["kind"] in ("landuse=farmland", "landuse=meadow")]
    farm_xz = [(x, z) for x, z in farm_xz if ter.h(x, z) < 700.0]          # valley farms, not the summit lodge

    def ok_wild(x, z, slope=0.45):
        i, j = int(z / 20), int(x / 20)
        return (0 <= i < n20 and 0 <= j < n20 and not bld_mask[i, j] and not near_road[i, j]
                and ter.steep(x, z, 10) < slope)

    def ok_farm(x, z):
        i, j = int(z / 20), int(x / 20)
        return (0 <= i < n20 and 0 <= j < n20 and not town_mask[i, j] and occ.free(x, z, 4.0, 2)
                and ter.steep(x, z, 10) < 0.25)

    def sample_near(cx, cz, rmax, test, tries=60):
        for _ in range(tries):
            t, d = prng.uniform(0, 2 * math.pi), rmax * math.sqrt(prng.random())
            x, z = cx + d * math.cos(t), cz + d * math.sin(t)
            if 30 < x < SIZE - 30 and 30 < z < SIZE - 30 and test(x, z):
                return x, z
        return None

    def herd_file(fname, n_terr, spacing, spec, test, centres_from=None, extra=0):
        van_t = open(os.path.join(a.vanilla, "env", fname)).read()
        color = re.search(r'<territory color="(\d+)"', van_t).group(1)
        cands = []
        if centres_from is not None:
            for cx, cz in centres_from:
                s = sample_near(cx, cz, 400.0, test)
                if s:
                    cands.append({"x": s[0], "z": s[1]})
        else:
            for _ in range(6000):
                x, z = prng.uniform(200, SIZE - 200), prng.uniform(200, SIZE - 200)
                if test(x, z):
                    cands.append({"x": x, "z": z})
        centres = pick(cands, n_terr, spacing, rng)
        lines_ = ['<?xml version="1.0" encoding="UTF-8"?>', "<territory-type>"]
        nzones = 0
        for c in centres:
            lines_.append('    <territory color="%s">' % color)
            for zname, (lo, hi), (rlo, rhi), reach in spec:
                for _ in range(prng.randint(lo, hi)):
                    if zname == "Water":
                        i, d = wgrid.nearest(c["x"], c["z"], 1200.0)
                        if i is None or d > 1200:
                            continue
                        s = sample_near(wgrid.xz[i, 0], wgrid.xz[i, 1], 150.0, lambda x, z: True)
                    else:
                        s = sample_near(c["x"], c["z"], reach, test)
                    if not s:
                        continue
                    attrs = 'dmin="0" dmax="2"' if zname.startswith("Zone_") else 'dmin="0" dmax="0"'
                    lines_.append('        <zone name="%s" smin="0" smax="0" %s x="%.1f" z="%.1f" r="%.0f"/>'
                                  % (zname, attrs, s[0], s[1], prng.uniform(rlo, rhi)))
                    nzones += 1
            lines_.append("    </territory>")
        lines_.append("</territory-type>")
        with open(os.path.join(a.out, "env", fname), "w", newline="\n") as fh:
            fh.write("\n".join(lines_) + "\n")
        return len(centres), nzones

    graze = lambda lo, hi, rl, rh, reach: ("Graze", (lo, hi), (rl, rh), reach)
    rest = lambda lo, hi, rl, rh, reach: ("Rest", (lo, hi), (rl, rh), reach)
    water = lambda lo, hi, rl, rh: ("Water", (lo, hi), (rl, rh), 0)
    wild_t = lambda x, z: ok_wild(x, z)
    gentle = lambda x, z: ok_wild(x, z, 0.3)
    farm_t = lambda x, z: ok_farm(x, z)
    plan = [
        ("bear_territories.xml", 34, 1300.0, [graze(4, 7, 100, 250, 600)], wild_t, None),
        ("red_deer_territories.xml", 26, 1500.0, [graze(3, 4, 60, 140, 450), rest(2, 3, 70, 120, 450),
                                                  water(1, 2, 60, 90)], gentle, None),
        ("roe_deer_territories.xml", 36, 1200.0, [graze(3, 4, 50, 150, 400), rest(2, 3, 60, 120, 400),
                                                  water(1, 2, 50, 90)], gentle, None),
        ("wild_boar_territories.xml", 30, 1300.0, [graze(3, 4, 50, 150, 400), rest(2, 3, 50, 120, 400),
                                                   water(1, 2, 50, 80)], wild_t, None),
        ("wolf_territories.xml", 10, 3000.0, [("HuntingGround", (5, 7), (150, 300), 1000), rest(3, 4, 120, 250, 800),
                                              water(1, 2, 50, 80)], wild_t, None),
        ("cattle_territories.xml", 12, 600.0, [graze(3, 4, 50, 120, 300), rest(1, 2, 50, 80, 250),
                                               water(1, 1, 50, 70)], farm_t, farm_xz),
        ("sheep_goat_territories.xml", 10, 600.0, [graze(3, 4, 50, 110, 300), rest(1, 2, 50, 80, 250)], farm_t,
         farm_xz),
        ("pig_territories.xml", 10, 600.0, [graze(2, 3, 50, 60, 200), rest(2, 3, 50, 60, 200), water(1, 1, 50, 50)],
         farm_t, farm_xz),
    ]
    for fname, n_terr, spacing, spec, test, centres in plan:
        t, nzn = herd_file(fname, n_terr, spacing, spec, test, centres)
        summary.append("%s: %d territories, %d zones" % (fname, t, nzn))
        print(summary[-1], flush=True)
    shutil.copy2(os.path.join(a.out, "env", "cattle_territories.xml"),
                 os.path.join(a.out, "env", "domestic_animals_territories.xml"))

    # Hens round the cabins and farms; foxes and hares across the wild, one territory each.
    hen_c = []
    for cid, members in clusters.items():
        if (len(members) >= 3 and buildings[members[0]]["cluster"] != "town"
                and buildings[members[0]]["tier"] <= 2):                   # no hens at the summit lodge
            hen_c.append([(buildings[i]["x"], buildings[i]["z"]) for i in members])
    lines_ = ['<?xml version="1.0" encoding="UTF-8"?>', "<territory-type>"]
    nh = 0
    hcolor = re.search(r'<territory color="(\d+)"', open(os.path.join(a.vanilla, "env", "hen_territories.xml")).read()).group(1)
    for pts in hen_c:
        lines_.append('    <territory color="%s">' % hcolor)
        for x, z in prng.sample(pts, min(len(pts), max(1, len(pts) // 6), 8)):
            lines_.append('        <zone name="Zone_hen" smin="0" smax="0" dmin="0" dmax="2" x="%.1f" z="%.1f" r="%.1f"/>'
                          % (x, z, prng.choice((75.0, 90.0, 105.0, 112.5))))
            nh += 1
        lines_.append("    </territory>")
    lines_.append("</territory-type>")
    with open(os.path.join(a.out, "env", "hen_territories.xml"), "w", newline="\n") as fh:
        fh.write("\n".join(lines_) + "\n")
    summary.append("hen_territories.xml: %d territories, %d zones" % (len(hen_c), nh))
    for fname, zname, count in (("fox_territories.xml", "Zone_fox", 380), ("hare_territories.xml", "Zone_Hare", 880)):
        color = re.search(r'<territory color="(\d+)"', open(os.path.join(a.vanilla, "env", fname)).read()).group(1)
        cands = []
        for _ in range(count * 8):
            x, z = prng.uniform(100, SIZE - 100), prng.uniform(100, SIZE - 100)
            i, j = int(z / 20), int(x / 20)
            if not town_mask[i, j] and ter.steep(x, z, 5) < 0.5:
                cands.append({"x": x, "z": z})
        got = pick(cands, count, 250.0 if zname == "Zone_fox" else 150.0, rng)
        lines_ = ['<?xml version="1.0" encoding="UTF-8"?>', "<territory-type>", '    <territory color="%s">' % color]
        lines_ += ['        <zone name="%s" smin="0" smax="0" dmin="0" dmax="2" x="%.1f" z="%.1f" r="50"/>'
                   % (zname, c["x"], c["z"]) for c in got]
        lines_ += ["    </territory>", "</territory-type>"]
        with open(os.path.join(a.out, "env", fname), "w", newline="\n") as fh:
            fh.write("\n".join(lines_) + "\n")
        summary.append("%s: %d zones" % (fname, len(got)))
    print("animals done", flush=True)

    # ------------------------------------------------ areaflags.map
    res = SIZE / FLAGS
    elev = ter.elev
    if elev.shape != (FLAGS, FLAGS):
        sys.exit("areaflags expects a %d grid of heights" % FLAGS)
    value = np.full((FLAGS, FLAGS), 1, np.uint8)
    for k, t in enumerate(TIER_HEIGHTS):
        value[elev >= t] = 2 << k
    usage = np.zeros((FLAGS, FLAGS), np.uint32)

    def paint(xz, radius, name):
        if len(xz):
            usage[near_mask(np.asarray(xz), radius, res, FLAGS)] |= np.uint32(1 << USAGE[name])
    zi =(np.arange(FLAGS) * res / zcell).astype(int)
    forest = zones[np.ix_(zi, zi)] != 0
    bx = lambda pred: [(b["x"], b["z"]) for b in buildings if pred(b)]
    paint(bx(lambda b: b["cluster"] == "town"), 80.0, "Town")
    paint(bx(lambda b: b["cluster"] != "town"), 60.0, "Village")
    # Hunting: patches of forest round the backcountry campsites, shelters and trailheads. Marking
    # the whole forest (94% of the map) made the economy divide by zero as it started; vanilla maps
    # mark only small areas with any usage.
    town_or_village = usage & np.uint32((1 << USAGE["Town"]) | (1 << USAGE["Village"]))
    camps = near_mask([(p["x"], p["z"]) for p in places if p["kind"] in HUNTING_PLACES], 150.0, res, FLAGS)
    usage[camps & forest & (town_or_village == 0)] |= np.uint32(1 << USAGE["Hunting"])
    paint(bx(lambda b: b["kind"] == "farm") + [(p["x"], p["z"]) for p in places if p["kind"] in
                                                ("landuse=farmland", "landuse=meadow")], 120.0, "Farm")
    paint(bx(lambda b: b["kind"] == "industrial"), 60.0, "Industrial")
    paint(bx(lambda b: b["kind"] == "police"), 50.0, "Police")
    paint(bx(lambda b: b["kind"] == "medic"), 50.0, "Medic")
    paint(bx(lambda b: b["kind"] == "fire"), 50.0, "Firefighter")
    paint(bx(lambda b: b["kind"] == "school"), 50.0, "School")
    paint(bx(lambda b: b["kind"] == "office"), 50.0, "Office")
    paint(bx(lambda b: b["kind"] == "church") + [(p["x"], p["z"]) for p in places
                                                  if p["kind"].startswith("historic=")], 60.0, "Historical")
    rivers = [(x, z) for ln in water_lines if ln.get("class") == "river" for x, z in ln["points"]]
    paint(rivers, 30.0, "Coast")
    # Usages this map has no buildings for. The economy adds an area's usage to every loot point in
    # it (vanilla's gas zones are how its buildings get ContaminatedArea loot), so: the gear vanilla
    # keeps for gas zones at the high heli crash sites and the convoys up top, medical supplies at
    # road crashes, prison gear in the police stations' cells, and the amusement-park gear round
    # Gatlinburg's lifts and tramway.
    paint([(c["x"], c["z"]) for c in heli if tier_at(c["x"], c["z"]) >= 3], 25.0, "ContaminatedArea")
    paint([(k["x"], k["z"]) for ev, name, kids, kind in scenes if kind == "convoy" and name.split("_")[2] == "4"
           for k in kids if k["loot"]], 12.0, "ContaminatedArea")
    paint([(k["x"], k["z"]) for ev, name, kids, kind in scenes if kind == "crash" for k in kids if k["loot"]],
          12.0, "Medic")
    paint(bx(lambda b: b["kind"] == "police"), 40.0, "Prison")
    geo = json.load(open(os.path.join(ROOT, "tools", "georef.json")))
    lifts = []
    for e in json.load(open(os.path.join(SRC, "mission", "osm_mapextras.json"), encoding="utf-8"))["elements"]:
        if e["type"] == "way" and e.get("tags", {}).get("aerialway") and "geometry" in e:
            for g in (e["geometry"][0], e["geometry"][-1]):
                x, z = utm(g["lat"], g["lon"], 17)
                lifts.append((x + geo["offset_x"], z + geo["offset_y"]))
    paint(lifts, 120.0, "Lunapark")
    with open(os.path.join(a.out, "areaflags.map"), "wb") as fh:
        fh.write(struct.pack("<6i", FLAGS, FLAGS, int(SIZE), int(SIZE), 32, 0))
        fh.write(usage.astype("<u4").tobytes())
        fh.write(value.tobytes())
    share = [100.0 * (value == (1 << k)).mean() for k in range(4)]
    summary.append("areaflags.map: tiers 1-4 cover %.0f / %.0f / %.0f / %.0f %% (heights %s m); usage: %s"
                   % (*share, "/".join("%.0f" % t for t in TIER_HEIGHTS),
                      ", ".join("%s %.1f%%" % (n, 100.0 * ((usage >> b) & 1).mean()) for n, b in USAGE.items()
                                if ((usage >> b) & 1).any())))
    print(summary[-1], flush=True)

    with open(os.path.join(SRC, "mission", "summary.txt"), "w", newline="\n") as fh:
        fh.write("Server mission dayzOffline.greatsmokymountains (tools/mission.py)\n\n" + "\n".join(summary) + "\n")
    print("done")


if __name__ == "__main__":
    main()
