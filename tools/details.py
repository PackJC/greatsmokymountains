"""The small things along the trails, the roads and the creeks: trail blazes, trail
signs, log footbridges, trailhead, picnic, overlook and campsite furniture and
shelters, springs and pumps, the old homestead orchards, the tramway and
chairlifts, street lamps, benches and mailboxes, power lines, ghost forests of
dead fir, laurel thickets, and mossy boulders and logs in the creeks.

    python tools/details.py source [ImageToPAA.exe]

Runs after tools/water_fit.py, on the final ground (source/buildings/elevation.npy),
and keeps clear of every object already placed (tools/mission.py's 2 m occupancy
grid) and of the roads. Writes:
  source/details/tb_markers.txt   blazes along every named trail, every 150 m or so and
                                  at its ends, in the trail's colour on the topo map
                                  (tools/topo_map.py: the Appalachian Trail red, the
                                  rest by name): on a blazed tree beside the path in the
                                  woods, a blazed stone or a painted pole in the open
  source/details/tb_footbridges.txt  log footbridges (tools/footbridge.py) where trails
                                  cross creeks, along the trail, bank to bank
  source/details/tb_lifts.txt     chairlift towers, stations, cables and chairs on
                                  OSM's aerialways (Ober's tramway to the map's edge)
  source/details/tb_street.txt    street lamps along the paved roads in town, benches
                                  and bins on the Parkway, mailboxes by the houses
  source/details/tb_power.txt     wooden power line poles and wires along the settled roads
  source/details/tb_nature.txt    dead firs standing and fallen up high, laurel along
                                  the creeks, mossy boulders in them, logs across them
  and it clears trees, bushes, deadwood and rocks from under the lifts, footbridges
  and power lines in source/forest and source/rocks (as tools/skybridge.py does).
  source/details/tb_signs.txt     trail signs (tools/trail_signs.py) at trailheads
                                  (the trail's name and up to three places along it,
                                  with miles) and where named trails meet (an arrow,
                                  the next place that way and its miles, per trail),
                                  distances along the trails themselves
  source/details/tb_props.txt     trailheads: a notice board, a bench, a bin and, by a
                                  car park, a privy; picnic areas: tables, bins, a
                                  privy; overlooks: benches facing the view; backcountry
                                  campsites and shelters: a camp table and chairs;
                                  ranger stations and LeConte Lodge: board and benches;
                                  and water: springs (Sakhal's stone spring, its pool
                                  drinkable) where creeks rise, near the trails first;
                                  hand pumps (wells: drink and fill) at campgrounds,
                                  picnic areas, ranger stations, the bigger trailheads,
                                  homesteads and farms; fountains in Gatlinburg
  source/details/tb_orchards.txt  apple, pear and plum trees at the old homesteads
                                  (OSM historic sites: the Roaring Fork and Greenbrier
                                  places) and by the farms' barns
  data/trailsigns/                the signs' models and textures (their PNGs in
                                  source/details/signs/)
  source/details/summary.txt and signs.png (every sign's face)
"""

import heapq
import json
import math
import os
import random
import sys
from collections import defaultdict

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import find_models  # noqa: E402
from mission import (MODEL_FOLDERS, OBSTACLE_FILES, ROAD_HALF_WIDTH, SIZE, BUILDING_FILES, Occupancy, Points,  # noqa: E402
                     Terrain, heading, kind_of, mark_objects, model_infos, osm_places, read_tb)
from footbridge import make_footbridge  # noqa: E402
from topo_map import TRAIL_COLOURS, trail_colour  # noqa: E402
from trail_signs import make_sign  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EASTING = 200000.0
SEED = 20261019
I2P = r"G:\SteamLibrary\steamapps\common\DayZ Tools\Bin\ImageToPAA\ImageToPAA.exe"
MILE = 1609.344

POLES = dict(zip(TRAIL_COLOURS, ["trail_woodenpole_r", "trail_woodenpole_y", "trail_woodenpole_g",
                                 "trail_woodenpole_b"]))
MARKER_EVERY = 150.0             # metres along a trail between poles
MARKER_END = 12.0                # first and last pole this far in from a trail's ends
MARKER_SIDE = 1.5                # off the path's centre line
MARKER_GAP = 60.0                # no two poles of a colour closer than this
SNAP = 12.0                      # a trail's end joins another trail this close
POI_SNAP = 150.0                 # a place counts as on a trail this close to it
MAX_MILES = 15.0                 # signs name places at most this far
SIGN_OFF = 2.5                   # signs stand this far from the junction or trail start
APPLE = ["t_malusdomestica_1s", "t_malusdomestica_2s_summer", "t_malusdomestica_3s_summer"]
PEAR = ["t_pyruscommunis_2s_summer", "t_pyruscommunis_3s_summer"]
PLUM = ["t_prunusdomestica_2s"]
SIGN_BOX = {"min": (-0.6, -0.3, -0.06), "max": (0.6, 2.0, 0.11), "center": (0.0, 0.0, 0.0)}
# Water: Sakhal's stone-walled spring (the plain one: its 36 numbered copies have Sakhal names
# carved over the spout), its pool a drinkable clean-water surface with the sound of running
# water; Chernarus's hand pumps (scripted wells: drink, fill, wash); the town fountain.
SPRING = "waterspring_sakhal"
PUMPS = ["misc_well_pump_yellow", "misc_well_pump_blue"]
FOUNTAIN = "misc_fountain"
SPRINGS = 70                     # at most this many, at creek heads
SPRING_GAP = 900.0               # metres between springs
SPRING_BACK = 6.0                # a spring stands this far up the slope from where its creek starts
TRAIL_NEAR = 300.0               # springs this close to a trail come first
# Kinds of places a sign may name, best first (when there are more than fit).
POI_RANK = ["peak", "lodge", "shelter", "falls", "gap", "overlook", "historic", "campsite", "trailhead"]
# Blazes, as Chernarus marks its trails: painted on a tree beside the path in the woods (spruce
# up high, beech below; Livonia's summer trees, vanilla's for green, which has no summer one),
# on a stone or a pole in the open.
ZONE_NAMES = ["open", "sprucefir", "northern", "cove", "oakpine", "mixed"]         # tools/forest.py ZONES
BLAZE_SIDE = 3.5                 # a blazed tree's trunk this far off the path
# Footbridges (tools/footbridge.py) where trails cross creeks, across the painted streambed
# (tools/paint_roads.py) and BRIDGE_BANK onto each bank.
FOOTBRIDGES = (8, 11, 14, 18, 24)
CREEK_WIDTH = {"seasonal": 3.0, "brook": 7.0, "stream": 8.0, "river": 15.0}
BRIDGE_BANK = 2.0
BRIDGE_PITCH, BRIDGE_HIGH = 12.0, 3.5    # steeper, or a deck higher than this over the creek: a ravine, left out
WIRE_CLEAR, CABLE_CLEAR = 4.5, 4.0       # a power wire's and a lift cable's lowest point over the ground
# Lifts on OSM's aerialways: Chernarus's chairlift (towers, stations, chairs), Livonia's power
# wire as its two cables.
LIFT_SPAN = 58.0                 # metres between towers, at most
LIFT_CLEAR = 6.0                 # trees cleared this far either side of a lift
LIFT_TOP, STATION_TOP = 13.0, 6.0    # cable heights over the ground at a tower and a station
LIFT_ARM = 2.0                   # the cables this far either side of the line
CHAIR_EVERY = 25.0
# Streets: in town (DENSE buildings within 150 m), lamps along the paved roads, benches and bins
# along the main ones downtown; mailboxes at the roadside by houses and cabins outside it.
DENSE, DOWNTOWN = 25, 35
LAMP_EVERY, BENCH_EVERY = 30.0, 60.0
MAILBOX_REACH, MAILBOX_BELOW = 45.0, 1000.0
# Power lines: Livonia's three-wire wooden poles along the settled roads (SETTLED buildings
# within 120 m), which keeps them out of the park.
POLE_EVERY, POLE_SINK = 45.0, 0.4
SETTLED = 3
WIRE_TOP = 9.15                  # wire ends this far over a pole's base; the wire model sags 0.82 m
POWER_CLEAR = 3.0                # trees cleared this far either side of a line
# Nature: ghost forests of dead firs up high, laurel thickets along creeks, mossy boulders in
# the creeks and logs fallen across them.
GHOST_FROM, GHOST_EVERY = 1750.0, 14.0
SNAGS = ["t_piceaabies_2d", "t_piceaabies_3d"]
FIR_LOGS = ["d_piceaabies_fallen", "d_piceaabies_fallenb", "d_piceaabies_fallend"]
LAUREL = "b_fagussylvatica_1f_summer"
LAUREL_BELOW, LAUREL_SHARE, LAUREL_EVERY = 1700.0, 0.20, 2.5
BOULDERS = ["stone6_moss", "stone7_moss", "stone9_moss", "stone10_moss"]
BOULDER_EVERY, BOULDER_CHANCE = 25.0, 0.45
CREEK_LOG_EVERY = 350.0
CREEK_LOGS = {"brook": ["d_piceaabies_fallen", "d_betulapendula_fallen"], "stream": ["d_piceaabies_fallen",
                                                                                     "d_fagussylvatica_fallen"]}


# OSM's misspellings, put right on the signs.
SPELLING = {"Cliif": "Cliff", "Rhodedendron": "Rhododendron", "Bunyon": "Bunion", "Chimney point": "Chimney Point",
            "Mt. le Conte - High Top": "Mt. Le Conte High Top", "Husky Gap": "Huskey Gap",
            "EEphraim": "Ephraim"}
SAME_SIGN = 800.0                # a junction sign saying the same as one this close is left out


def nice(name, trailhead=False):
    name = name.replace("Mount ", "Mt. ").replace("Mountain", "Mtn.").replace("  ", " ").strip()
    for wrong, right in SPELLING.items():
        name = name.replace(wrong, right)
    name = name.replace("Concession Horse Trail", "Horse Trail")
    if "#" in name:                                   # backcountry campsites: "Porters Flat #31"
        return "Campsite #" + name.split("#")[1].strip()
    if trailhead:                                     # "Rainbow Falls Trail Trailhead" -> "Rainbow Falls Trailhead"
        name = name.replace(" Trail Trailhead", " Trailhead")
        if not name.endswith("Trailhead"):
            name = name.replace(" Trail", "") + " Trailhead"
    return name


def trail_title(name):
    return nice(name).upper()


def main():
    src = sys.argv[1]
    i2p = sys.argv[2] if len(sys.argv) > 2 else I2P
    out = os.path.join(src, "details")
    os.makedirs(out, exist_ok=True)
    rng = random.Random(SEED)
    ter = Terrain(np.load(os.path.join(src, "buildings", "elevation.npy")))
    zones = np.load(os.path.join(src, "forest", "zones.npy"))[::-1]          # row 0 south
    zcell = SIZE / zones.shape[0]

    def zone_at(x, z):
        return int(zones[min(max(int(z / zcell), 0), zones.shape[0] - 1), min(max(int(x / zcell), 0), zones.shape[1] - 1)])

    def open_ground(x, z):
        return zone_at(x, z) == 0

    bridge_dir = os.path.join(ROOT, "data", "footbridges")
    bridge_tpl = {length: make_footbridge(length, bridge_dir) for length in FOOTBRIDGES}
    models = find_models(MODEL_FOLDERS)
    infos = model_infos(models)

    def model_info(tpl):
        return SIGN_BOX if tpl.startswith("gsm_sign_") else infos(tpl)

    # Everything already placed, and the buildings.
    occ = Occupancy()
    codes = {}
    buildings = []
    for rel in OBSTACLE_FILES:
        c, rows = read_tb(os.path.join(src, rel), codes)
        names = {v: k for k, v in codes.items()}
        for code in np.unique(c):
            mark_objects(occ, names[code], rows[c == code], model_info)
        if rel in BUILDING_FILES:
            buildings += [(names[k], r[0], r[1]) for k, r in zip(c, rows)]
        print("occupancy: %s (%d)" % (rel, len(rows)), flush=True)

    # Roads (not trails), to keep everything off them.
    lines = json.load(open(os.path.join(src, "roads", "lines.json")))
    rp, rw = [], []
    for ln in lines:
        if ln["group"] == "trails" or ln["family"] not in ROAD_HALF_WIDTH:
            continue
        pts = np.array(ln["points"])
        for a, b in zip(pts[:-1], pts[1:]):
            n = max(1, int(np.hypot(*(b - a)) / 4.0))
            for t in np.arange(n) / n:
                rp.append(a + (b - a) * t)
                rw.append(ROAD_HALF_WIDTH[ln["family"]])
    roads = Points(np.array(rp), 50.0)
    road_w = np.array(rw)

    def off_road(x, z, margin):
        near = roads.within(x, z, 6.0 + margin)
        return not near or all(math.hypot(*(roads.xz[i] - (x, z))) > road_w[i] + margin for i in near)

    def nearest_road(x, z):
        i, d = roads.nearest(x, z, 2000.0)
        return (roads.xz[i], d) if i is not None else (None, float("inf"))

    placed = defaultdict(list)                   # file -> rows (tpl, x, z, yaw, pitch, roll, scale, rel)
    clear = []                                   # (a, b, width): corridors to clear of trees, bushes, deadwood, rocks

    def put(kind, tpl, x, z, yaw, scale=1.0, sink=0.0, pitch=0.0, roll=0.0, rel=None):
        """rel: the model's origin over the ground; by default its own base on the ground, less sink."""
        if rel is None:
            rel = (0.0 if tpl.startswith("gsm_sign_") else model_info(tpl)["center"][1] * scale) - sink
        placed[kind].append((tpl, x, z, yaw % 360.0, pitch, roll, scale, rel))
        mark_objects(occ, tpl, np.array([[x, z, yaw, pitch, roll, scale, rel]]), model_info)

    def spot(x, z, r, reach, max_slope=0.3, margin=1.0, bits=3, avoid=()):
        """The nearest clear, flat enough spot to (x, z) within reach, off the roads."""
        for d in np.arange(0.0, reach + 0.1, 1.0):
            steps = 1 if d == 0 else int(2 * math.pi * d / 1.0)
            t0 = rng.uniform(0, 2 * math.pi)
            for k in range(steps):
                t = t0 + 2 * math.pi * k / steps
                px, pz = x + d * math.cos(t), z + d * math.sin(t)
                if occ.free(px, pz, r, bits) and ter.steep(px, pz, r + 1.0) <= max_slope \
                        and off_road(px, pz, margin + r) and all(math.hypot(px - u, pz - v) > 2.0 for u, v in avoid):
                    return px, pz
        return None

    # ------------------------------------------------------------- the trail network
    trails = [ln for ln in lines if ln["group"] == "trails" and len(ln["points"]) > 1]
    key_id, xy = {}, []

    def vid(x, z):
        k = (round(x * 2), round(z * 2))                     # OSM's shared nodes become one
        if k not in key_id:
            key_id[k] = len(xy)
            xy.append((x, z))
        return key_id[k]
    line_ids = [[vid(x, z) for x, z in ln["points"]] for ln in trails]
    xy = np.array(xy)
    grid = Points(xy, 25.0)
    merge = {}
    for ids in line_ids:                                    # a trail's ends join the trail they meet
        own = set(ids)
        for e in (ids[0], ids[-1]):
            near = [j for j in grid.within(xy[e, 0], xy[e, 1], SNAP) if j not in own]
            if near:
                merge[e] = min(near, key=lambda j: np.hypot(*(xy[j] - xy[e])))

    def root(v):
        seen = 0
        while v in merge and seen < 20:
            v, seen = merge[v], seen + 1
        return v
    adj = defaultdict(list)
    for ids, ln in zip(line_ids, trails):
        ids = [root(v) for v in ids]
        for a, b in zip(ids[:-1], ids[1:]):
            if a != b:
                d = float(np.hypot(*(xy[b] - xy[a])))
                adj[a].append((b, d, ln.get("name") or ""))
                adj[b].append((a, d, ln.get("name") or ""))
    names_at = {v: {n for _, _, n in e if n} for v, e in adj.items()}

    def dijkstra(s, limit=MAX_MILES * MILE):
        dist, pred = {s: 0.0}, {s: None}
        q = [(0.0, s)]
        while q:
            d, v = heapq.heappop(q)
            if d > dist.get(v, 1e18) or d > limit:
                continue
            for w, l, _ in adj[v]:
                nd = d + l
                if nd < dist.get(w, 1e18):
                    dist[w], pred[w] = nd, v
                    heapq.heappush(q, (nd, w))
        return dist, pred

    def path_from(pred, v):
        out_ = [v]
        while pred[out_[-1]] is not None:
            out_.append(pred[out_[-1]])
        return out_[::-1]                                  # source first

    vgrid = Points(xy[list(adj)], 50.0)
    vlist = list(adj)

    def snap(x, z, r):
        i, d = vgrid.nearest(x, z, r)
        return (vlist[i], d) if i is not None and d <= r else (None, d)

    # Places a sign can name, on the network.
    places = osm_places()
    kinds = {"natural=peak": "peak", "natural=saddle": "gap", "amenity=shelter": "shelter",
             "tourism=alpine_hut": "lodge", "tourism=viewpoint": "overlook", "tourism=camp_site": "campsite",
             "highway=trailhead": "trailhead"}
    pois = []
    for p in places:
        kind = kinds.get(p["kind"]) or ("historic" if p["kind"].startswith("historic=") else None)
        if not kind or not p["name"] or p["name"].lower() in ("corn crib",):
            continue
        if kind == "shelter" and "Shelter" not in p["name"]:
            continue
        if kind == "campsite" and "#" not in p["name"]:
            continue
        pois.append({"name": nice(p["name"], kind == "trailhead"), "kind": kind, "x": p["x"], "z": p["z"]})
    geo = json.load(open(os.path.join(ROOT, "tools", "georef.json")))
    from geo import utm
    for e in json.load(open(os.path.join(src, "water", "osm_water.json"), encoding="utf-8"))["elements"]:
        t = e.get("tags", {})
        if e["type"] == "node" and t.get("waterway") == "waterfall" and t.get("name"):
            x, z = utm(e["lat"], e["lon"], 17)
            pois.append({"name": nice(t["name"]), "kind": "falls", "x": x + geo["offset_x"], "z": z + geo["offset_y"]})
    best = {}
    for p in pois:
        v, d = snap(p["x"], p["z"], POI_SNAP)
        if v is not None and (p["name"] not in best or d < best[p["name"]]["d"]):
            best[p["name"]] = dict(p, v=v, d=d)
    pois = list(best.values())
    poi_at = defaultdict(list)
    for p in pois:
        poi_at[p["v"]].append(p)

    def ranked(ps):
        return sorted(ps, key=lambda p: (POI_RANK.index(p["kind"]), p["dist"]))

    def bearing_along(pred, v, ahead=25.0, dist=None):
        """Bearing from the source toward v along the path, taken about `ahead` metres out."""
        pth = path_from(pred, v)
        s = pth[0]
        for w in pth[1:]:
            if dist[w] >= ahead:
                return heading(*(xy[w] - xy[s]))
        return heading(*(xy[pth[-1]] - xy[s])) if len(pth) > 1 else 0.0

    # ------------------------------------------------------------- signs
    i2p = i2p if os.path.isfile(i2p) else None
    model_dir = os.path.join(ROOT, "data", "trailsigns")
    png_dir = os.path.join(out, "signs")
    for d in (model_dir, png_dir):
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.startswith("gsm_sign_"):
                    os.remove(os.path.join(d, f))
    signs = []                                             # (template, title, rows)

    def sign(title, rows, x, z, yaw, why):
        name = "gsm_sign_%02d" % (len(signs) + 1)
        make_sign(name, title, rows, model_dir, png_dir, i2p, seed=len(signs))
        put("signs", name, x, z, yaw, sink=0.0)
        signs.append((name, title, rows, why))

    trailhead_v = []
    for p in sorted((p for p in places if p["kind"] == "highway=trailhead"), key=lambda p: p["name"]):
        v, d = snap(p["x"], p["z"], 120.0)
        if v is None or not names_at.get(v):
            continue
        names = sorted(names_at[v], key=lambda n: (n.replace(" Trail", "") not in p["name"], n))
        trail = names[0]
        dist, pred = dijkstra(v)
        cands = []
        for w, ps in poi_at.items():
            if w in dist and dist[w] > 0.1 * MILE and trail in names_at.get(w, ()):
                cands += [dict(q, dist=dist[w]) for q in ps if q["kind"] != "trailhead"]
        cands = ranked(cands)[:3]
        if len(cands) < 3:                                 # then the nearest places on the trails it leads to
            more = [dict(q, dist=dist[w]) for w, ps in poi_at.items() if w in dist and 0.1 * MILE < dist[w] < 8 * MILE
                    for q in ps if q["kind"] != "trailhead" and q["name"] not in {c["name"] for c in cands}]
            cands += sorted(more, key=lambda q: q["dist"])[:3 - len(cands)]
        cands = sorted(cands, key=lambda q: q["dist"])
        if not cands:
            continue
        # Stand beside the trail's start, facing the way people arrive (from the road).
        road_pt, _ = nearest_road(*xy[v])
        come = road_pt if road_pt is not None else np.array([p["x"], p["z"]])
        towards = come - xy[v]
        towards = towards / (np.hypot(*towards) or 1.0)
        s = spot(*(xy[v] + towards * SIGN_OFF), 0.4, 8.0, 0.6, 0.5)
        if not s:
            continue
        sign(trail_title(trail), [("", q["name"], q["dist"] / MILE) for q in cands], s[0], s[1],
             heading(*(come - np.array(s))), "trailhead: " + p["name"])
        trailhead_v.append(v)

    junctions = [v for v, ns in names_at.items() if len(ns) >= 2]
    taken = [xy[v] for v in trailhead_v]
    said = []                                              # (title, where) of the junction signs so far
    for v in sorted(junctions, key=lambda v: (-len(names_at[v]), tuple(xy[v]))):
        if any(np.hypot(*(xy[v] - t)) < 60.0 for t in taken):
            continue
        dist, pred = dijkstra(v)
        hops = defaultdict(list)                           # first step out of the junction -> places that way
        for w, ps in poi_at.items():
            if w in dist and dist[w] > 0.1 * MILE:
                first = path_from(pred, w)[1]
                hops[first] += [dict(q, dist=dist[w], w=w) for q in ps]
        rows = []
        for first, ps in hops.items():
            q = min(ps, key=lambda q: q["dist"])
            rows.append((bearing_along(pred, q["w"], dist=dist), q))
        if len(rows) < 2:
            continue
        # The sign stands in the widest gap between the ways out, facing the junction.
        ways = sorted(heading(*(xy[w] - xy[v])) for w, _, _ in adj[v])
        gaps = [((ways[(k + 1) % len(ways)] - ways[k]) % 360 or 360, ways[k]) for k in range(len(ways))]
        width, start = max(gaps)
        g = (start + width / 2) % 360
        gr = math.radians(g)
        s = spot(xy[v][0] + SIGN_OFF * math.sin(gr), xy[v][1] + SIGN_OFF * math.cos(gr), 0.4, 3.0, 0.6, 0.5)
        if not s:
            continue
        out_rows = []
        for b, q in sorted(rows, key=lambda r: ((r[0] - g + 180) % 360 - 180)):
            rel = (b - g + 180) % 360 - 180                    # the way's bearing, the reader facing the sign
            way = "ahead" if abs(rel) < 30 else ("right" if rel > 0 else "left")
            out_rows.append((way, q["name"], q["dist"] / MILE))
        title = " / ".join(trail_title(n) for n in sorted(names_at[v], key=len)[:2])
        if any(t == title and np.hypot(*(xy[v] - w)) < SAME_SIGN for t, w in said):
            continue
        sign(title, out_rows[:4], s[0], s[1], heading(*(xy[v] - np.array(s))), "junction")
        taken.append(xy[v])
        said.append((title, xy[v]))

    # ------------------------------------------------------------- footbridges where trails cross creeks
    water = json.load(open(os.path.join(src, "water", "lines.json")))
    wseg = defaultdict(list)                               # 50 m cell -> creek segments in it
    for ln in water:
        pts = np.array(ln["points"])
        for a, b in zip(pts[:-1], pts[1:]):
            lo, hi = np.minimum(a, b) // 50, np.maximum(a, b) // 50
            for i in range(int(lo[0]), int(hi[0]) + 1):
                for j in range(int(lo[1]), int(hi[1]) + 1):
                    wseg[(i, j)].append((a, b, ln["class"]))

    def cross(p, q, a, b):
        r, s = q - p, b - a
        den = r[0] * s[1] - r[1] * s[0]
        if abs(den) < 1e-9:
            return None
        t = ((a[0] - p[0]) * s[1] - (a[1] - p[1]) * s[0]) / den
        u = ((a[0] - p[0]) * r[1] - (a[1] - p[1]) * r[0]) / den
        return p + t * r if 0 <= t <= 1 and 0 <= u <= 1 else None
    road_bridges = read_tb(os.path.join(src, "buildings", "tb_bridges.txt"), {})[1][:, :2]
    crossings = []
    for ln in trails:
        pts = np.array(ln["points"])
        for p, q in zip(pts[:-1], pts[1:]):
            if np.hypot(*(q - p)) < 1e-6:
                continue
            lo, hi = np.minimum(p, q) // 50, np.maximum(p, q) // 50
            for i in range(int(lo[0]), int(hi[0]) + 1):
                for j in range(int(lo[1]), int(hi[1]) + 1):
                    for a, b, cls in wseg.get((i, j), ()):
                        hit = cross(p, q, a, b)
                        if hit is not None and np.hypot(*(b - a)) > 1e-6:
                            crossings.append((hit, (q - p) / np.hypot(*(q - p)), (b - a) / np.hypot(*(b - a)), cls))
    bridges = []
    for c, tdir, cdir, cls in crossings:
        if any(np.hypot(*(c - o)) < 15.0 for o in bridges) or not off_road(c[0], c[1], 4.0) or \
                (len(road_bridges) and np.hypot(*(road_bridges - c).T).min() < 25.0):
            continue
        # Along the trail, which comes down to the creek at a walkable grade; long enough to
        # cross the streambed at the angle the trail meets it.
        sin = abs(tdir[0] * cdir[1] - tdir[1] * cdir[0])
        if sin < 0.5:
            continue                                       # a trail running along the creek
        length = next((n for n in FOOTBRIDGES if n >= CREEK_WIDTH[cls] / sin + 2 * BRIDGE_BANK), None)
        if length is None:
            continue
        n = tdir
        a_end, b_end = c - n * length / 2, c + n * length / 2
        ha, hb, hc = ter.h(*a_end), ter.h(*b_end), ter.h(*c)
        deck = max((ha + hb) / 2 + 0.15, hc + 1.0)         # resting on both banks, clear of the water
        pitch = -math.degrees(math.atan2(hb - ha, length))
        if abs(pitch) > BRIDGE_PITCH or deck - hc > BRIDGE_HIGH:
            continue                                       # a ravine, not a creek crossing
        put("footbridges", bridge_tpl[length], c[0], c[1], heading(*n), pitch=pitch, rel=deck - hc)
        clear.append((a_end, b_end, 1.5))
        bridges.append(c)

    # ------------------------------------------------------------- trail markers: blazes
    def blaze_tree(zone, letter):
        kind = "t_piceaabies_3f_trail_" if zone in ("sprucefir", "northern") else "t_fagussylvatica_2sb_trail_"
        return kind + letter + ("" if letter == "g" else "_summer")
    marks = defaultdict(list)
    for ln in trails:
        name = ln.get("name") or ""
        if not name:
            continue
        pole = POLES[trail_colour(name)]
        letter = pole[-1]
        pts = np.array(ln["points"])
        seg = np.diff(pts, axis=0)
        segl = np.hypot(seg[:, 0], seg[:, 1])
        cum = np.concatenate([[0.0], np.cumsum(segl)])
        if cum[-1] < 2 * MARKER_END:
            continue
        n = max(1, int(round((cum[-1] - 2 * MARKER_END) / MARKER_EVERY)))
        for k, s0 in enumerate(np.linspace(MARKER_END, cum[-1] - MARKER_END, n + 1)):
            for ds in (0.0, 4.0, -4.0, 8.0, -8.0):
                s = min(max(s0 + ds, 0.0), cum[-1] - 1e-3)
                i = min(int(np.searchsorted(cum, s, "right") - 1), len(seg) - 1)
                if segl[i] == 0:
                    continue
                dx, dz = seg[i] / segl[i]
                cx, cz = pts[i] + (s - cum[i]) / segl[i] * seg[i]
                sgn = 1 if (k + int(ds != 0)) % 2 == 0 else -1
                if any(math.hypot(cx - u, cz - w) < MARKER_GAP for u, w in marks[letter]) or \
                        any(math.hypot(cx - u, cz - w) < 10.0 for u, w in bridges):
                    break
                zone = ZONE_NAMES[zone_at(cx, cz)]
                x, z = cx + dz * BLAZE_SIDE * sgn, cz - dx * BLAZE_SIDE * sgn
                if zone != "open" and occ.free(x, z, 1.5) and off_road(x, z, 2.0):
                    sc = rng.uniform(0.9, 1.1)
                    put("markers", blaze_tree(zone, letter), x, z, rng.uniform(0, 360), sc, sink=0.3 * sc)
                    marks[letter].append((cx, cz))
                    break
                x, z = cx + dz * MARKER_SIDE * sgn, cz - dx * MARKER_SIDE * sgn
                tpl = "stone5_trail_" + letter if zone == "open" and k % 2 == 0 else pole
                if occ.free(x, z, 0.8 if tpl.startswith("stone") else 0.4) and off_road(x, z, 1.0):
                    put("markers", tpl, x, z, heading(cx - x, cz - z), sink=0.25 if tpl.startswith("stone") else 0.0)
                    marks[letter].append((cx, cz))
                    break

    # ------------------------------------------------------------- furniture where people stop
    def near_parking(x, z, r):
        return any(math.hypot(p["x"] - x, p["z"] - z) < r for p in places if p["kind"] == "amenity=parking")

    def furnish(x, z, items, reach=25.0, face=None):
        got = []
        for tpl, r in items:
            s = spot(x, z, r, reach, 0.25, 1.0, avoid=got)
            if s:
                yaw = heading(face[0] - s[0], face[1] - s[1]) if face is not None else rng.uniform(0, 360)
                put("props", tpl, s[0], s[1], yaw)
                got.append(s)
        return len(got)

    def view_from(x, z):
        """Bearing of the widest drop: the way an overlook looks."""
        best_b, best_drop = 0.0, -1e9
        h0 = ter.h(x, z)
        for b in range(0, 360, 15):
            br = math.radians(b)
            drop = np.mean([h0 - ter.h(min(max(x + d * math.sin(br), 0), SIZE - 1), min(max(z + d * math.cos(br), 0), SIZE - 1))
                            for d in (100, 200, 400)])
            if drop > best_drop:
                best_b, best_drop = b, drop
        return best_b

    stops = defaultdict(int)
    for p in places:
        x, z, k, nm = p["x"], p["z"], p["kind"], p["name"]
        road_pt, _ = nearest_road(x, z)
        face = road_pt if road_pt is not None else None
        if k == "highway=trailhead":
            items = [("misc_noticeboard1", 0.8), ("misc_bench1", 0.9), ("garbage_bin", 0.5)]
            if near_parking(x, z, 150.0):
                items.append(("misc_toilet_dry", 1.4))
            stops["trailheads"] += furnish(x, z, items, 20.0, face) > 0
        elif k == "tourism=picnic_site" or (k == "amenity=shelter" and "Picnic" in nm):
            items = [("misc_trailroof_big", 2.6)] * ("Pavilion" in nm) + [("misc_table", 1.2)] * 6 + \
                [("garbage_bin", 0.5)] * 2 + [("misc_toilet_dry", 1.4)]
            stops["picnic areas"] += furnish(x, z, items, 40.0) > 0
        elif k == "tourism=viewpoint":
            b = math.radians(view_from(x, z))
            got = 0
            for _ in range(2):
                s = spot(x, z, 0.9, 12.0, 0.3, 1.0)
                if s:
                    put("props", "misc_bench1", s[0], s[1], math.degrees(b))
                    got += 1
            got += furnish(x, z, [("garbage_bin", 0.5)], 12.0)
            stops["overlooks"] += got > 0
        elif k == "tourism=camp_site" and "#" in nm:
            stops["backcountry campsites"] += furnish(x, z, [("misc_table_camp", 1.1), ("misc_chair_camp1", 0.4),
                                                             ("misc_chair_camp2", 0.4)], 15.0) > 0
        elif k == "tourism=camp_site" and "Campground" in nm:
            items = [("misc_table", 1.2)] * 4 + [("garbage_bin", 0.5)] * 2 + [("misc_toilet_dry", 1.4)]
            stops["campgrounds"] += furnish(x, z, items, 40.0) > 0
        elif k == "amenity=shelter" and "Shelter" in nm:
            stops["trail shelters"] += furnish(x, z, [("misc_trailroof_big", 2.6), ("misc_table_camp", 1.1),
                                                      ("misc_bench1", 0.9)], 15.0) > 0
        elif k == "amenity=ranger_station":
            stops["ranger stations"] += furnish(x, z, [("misc_noticeboard2", 0.8), ("misc_bench1", 0.9)], 25.0, face) > 0
        elif k == "tourism=alpine_hut":
            stops["LeConte Lodge"] += furnish(x, z, [("misc_bench1", 0.9), ("misc_bench1", 0.9)], 25.0) > 0

    # ------------------------------------------------------------- orchards
    sites = []
    for p in places:
        if p["kind"].startswith("historic=") and p["name"].lower() not in ("corn crib",) and \
                all(math.hypot(p["x"] - s[0], p["z"] - s[1]) > 150.0 for s in sites):
            sites.append((p["x"], p["z"], "homestead"))
    for tpl, x, z in buildings:
        if kind_of(tpl) == "farm" and all(math.hypot(x - s[0], z - s[1]) > 150.0 for s in sites):
            sites.append((x, z, "farm"))
    orchards, trees = 0, 0
    for x, z, why in sites:
        got = []
        for k in range(rng.randint(5, 8)):
            t, d = rng.uniform(0, 2 * math.pi), rng.uniform(12.0, 45.0)
            px, pz = x + d * math.cos(t), z + d * math.sin(t)
            s = None
            for want_open in (True, False):
                s = spot(px, pz, 2.5, 8.0, 0.35, 3.0, avoid=[(u, v) for u, v in got for _ in (0,)])
                if s and (open_ground(*s) or not want_open) and all(math.hypot(s[0] - u, s[1] - v) > 6.5 for u, v in got):
                    break
                s = None
            if not s:
                continue
            roll = rng.random()
            tpl = rng.choice(APPLE if roll < 0.7 else PEAR if roll < 0.9 else PLUM)
            scale = rng.uniform(0.85, 1.1)
            put("orchards", tpl, s[0], s[1], rng.uniform(0, 360), scale, sink=0.15 * scale)
            got.append(s)
        orchards += len(got) > 0
        trees += len(got)

    # ------------------------------------------------------------- water: springs, pumps, fountains
    wpts =[(x, z, k) for k, ln in enumerate(water) for x, z in ln["points"]]
    wgrid = Points(np.array([(x, z) for x, z, _ in wpts]), 50.0)
    heads = []
    for k, ln in enumerate(water):
        if ln["class"] not in ("brook", "stream") or len(ln["points"]) < 3:
            continue
        pts = np.array(ln["points"])
        if ter.h(*pts[-1]) > ter.h(*pts[0]):
            pts = pts[::-1]                                # the upper end is where it rises
        if not (100.0 < pts[0][0] < SIZE - 100.0 and 100.0 < pts[0][1] < SIZE - 100.0) or \
                any(wpts[i][2] != k for i in wgrid.within(*pts[0], 20.0)):
            continue                                       # another creek's line runs on up from here
        k = min(len(pts) - 1, max(1, int(np.searchsorted(np.cumsum(np.hypot(*np.diff(pts, axis=0).T)), 8.0))))
        down = pts[k] - pts[0]
        down = down / (np.hypot(*down) or 1.0)
        near_trail = vgrid.nearest(*pts[0], TRAIL_NEAR)[1] <= TRAIL_NEAR
        heads.append((not near_trail, rng.random(), pts[0], down))
    heads.sort(key=lambda h: h[:2])
    springs = []
    for _, _, p, down in heads:
        if len(springs) >= SPRINGS or any(np.hypot(*(p - s)) < SPRING_GAP for s in springs):
            continue
        s = spot(*(p - down * SPRING_BACK), 1.6, 4.0, 0.45, 2.0)
        if s:
            put("props", SPRING, s[0], s[1], heading(*down), sink=0.1)  # its pool and spout face downstream
            springs.append(np.array(s))
    pumps = 0
    for p in places:
        k, nm = p["kind"], p["name"]
        if k in ("tourism=picnic_site", "amenity=ranger_station") or (k == "tourism=camp_site" and "Campground" in nm) \
                or (k == "highway=trailhead" and near_parking(p["x"], p["z"], 150.0)):
            pumps += furnish(p["x"], p["z"], [(rng.choice(PUMPS), 1.0)], 30.0)
    for x, z, why in sites:                                # every homestead and farm had its pump
        pumps += furnish(x, z, [(rng.choice(PUMPS), 1.0)], 30.0)
    fountains, spots_f = 0, []
    for p in places:                                       # Gatlinburg's parks and attractions
        if fountains < 4 and p["kind"] in ("leisure=park", "tourism=attraction") and ter.h(p["x"], p["z"]) < 560 \
                and all(math.hypot(p["x"] - u, p["z"] - v) > 250.0 for u, v in spots_f):
            got = furnish(p["x"], p["z"], [(FOUNTAIN, 2.2)], 40.0)
            fountains += got
            if got:
                spots_f.append((p["x"], p["z"]))
    stops["springs"], stops["water pumps"], stops["fountains"] = len(springs), pumps, fountains

    def along(pts, cum, s):
        """Point and unit direction s metres along a polyline."""
        s = min(max(s, 0.0), cum[-1] - 1e-6)
        i = min(int(np.searchsorted(cum, s, "right") - 1), len(pts) - 2)
        d = pts[i + 1] - pts[i]
        n = np.hypot(*d) or 1.0
        return pts[i] + d * (s - cum[i]) / n, d / n

    def polyline(points):
        pts = np.array(points, float)
        return pts, np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])

    def lowest_gap(a, b, ha, hb):
        """The least height of a sagging wire from a (height ha) to b (hb) over the ground."""
        return min(ha + (hb - ha) * f - 0.82 * 4 * f * (1 - f) - ter.h(*(a + (b - a) * f)) for f in np.linspace(0, 1, 21))

    def wire(kind, tpl, a, b, ha, hb):
        """A 50 m wire model (Livonia's power wire) hung from a at height ha to b at hb: its centre
        0.41 m under the line between its ends (it sags 0.82 m), scaled to the span, tilted to it."""
        span = float(np.hypot(*(b - a)))
        m = (a + b) / 2
        put(kind, tpl, m[0], m[1], heading(*(b - a)), scale=span / 50.0,
            pitch=-math.degrees(math.atan2(hb - ha, span)), rel=(ha + hb) / 2 - 0.41 - ter.h(*m))

    # ------------------------------------------------------------- lifts: the tramway, the SkyLift, the gondola
    lifts = {}
    for e in json.load(open(os.path.join(src, "mission", "osm_mapextras.json"), encoding="utf-8"))["elements"]:
        t = e.get("tags", {})
        if e["type"] != "way" or t.get("aerialway") not in ("cable_car", "chair_lift", "gondola") or "geometry" not in e:
            continue
        pts = [np.array((utm(g["lat"], g["lon"], 17)[0] + geo["offset_x"], utm(g["lat"], g["lon"], 17)[1] + geo["offset_y"]))
               for g in e["geometry"]]
        inside = lambda p: 60.0 <= p[0] <= SIZE - 60.0 and 60.0 <= p[1] <= SIZE - 60.0   # noqa: E731
        if not inside(pts[0]):
            pts = pts[::-1]                                # start from its end on the map
        if not inside(pts[0]):
            continue
        ends = [True, True]                                # a station at each end it has on the map
        for k in range(1, len(pts)):
            if not inside(pts[k]):                         # Ober's tramway runs off the map: stop at the edge
                a, b = pts[k - 1], pts[k]
                f = min([1.0] + [(lim - a[i]) / (b[i] - a[i]) for i in (0, 1) for lim in (60.0, SIZE - 60.0)
                                 if b[i] != a[i] and 0 < (lim - a[i]) / (b[i] - a[i]) < 1])
                pts = pts[:k] + [a + (b - a) * f]
                ends[1] = False
                break
        pts, cum = polyline(pts)
        if cum[-1] < 60:
            continue
        def tower_at(s0, reach=15.0):
            """Where along the line near s0 a tower can stand: off the roads, clear of buildings."""
            for ds in [0.0] + [v * sgn for v in np.arange(3.0, reach + 0.1, 3.0) for sgn in (1, -1)]:
                s = min(max(s0 + ds, 1.0), cum[-1] - 1.0)
                p, _ = along(pts, cum, s)
                if off_road(p[0], p[1], 2.5) and occ.free(p[0], p[1], 2.5, 2):
                    return s
            return None
        n = int(math.ceil(cum[-1] / LIFT_SPAN))
        at_s = [0.0] + [s for s in (tower_at(v) for v in np.linspace(0.0, cum[-1], n + 1)[1:-1]) if s is not None] + \
            [cum[-1]]
        top = lambda k: ter.h(*along(pts, cum, at_s[k])[0]) + (STATION_TOP if (k == 0 and ends[0]) or  # noqa: E731
                                                                 (k == len(at_s) - 1 and ends[1]) else LIFT_TOP)
        for _ in range(60):                                # a tower more wherever the cable comes near the ground
            bad = [k for k in range(len(at_s) - 1) if at_s[k + 1] - at_s[k] > 20.0 and lowest_gap(
                along(pts, cum, at_s[k])[0], along(pts, cum, at_s[k + 1])[0], top(k), top(k + 1)) < CABLE_CLEAR]
            if not bad:
                break
            s = tower_at((at_s[bad[0]] + at_s[bad[0] + 1]) / 2, 8.0)
            if s is None or s in at_s:
                break
            at_s = sorted(at_s + [s])
        sup = []
        for k, s in enumerate(at_s):
            p, d = along(pts, cum, s)
            if (k == 0 and ends[0]) or (k == len(at_s) - 1 and ends[1]):   # stations, facing along the line
                if occ.free(p[0], p[1], 3.0, 2):
                    put("lifts", "cableway_base", p[0], p[1], heading(*(d if k == 0 else -d)))
            else:
                put("lifts", "cableway_tower", p[0], p[1], heading(*d))
            sup.append((p, top(k)))
        chairs = 0
        for (pa, ha), (pb, hb) in zip(sup[:-1], sup[1:]):
            u = (pb - pa) / np.hypot(*(pb - pa))
            side = np.array([u[1], -u[0]])
            for lat, way in ((LIFT_ARM, 1), (-LIFT_ARM, -1)):   # up one side, down the other
                a, b = pa + side * lat, pb + side * lat
                wire("lifts", "power_wire_50_main", a, b, ha, hb)
                span = np.hypot(*(b - a))
                for f in np.arange(CHAIR_EVERY / 2, span, CHAIR_EVERY) / span:
                    q = a + (b - a) * f
                    grip = ha + (hb - ha) * f - 0.82 * 4 * f * (1 - f)
                    if grip - 3.36 - ter.h(*q) < 1.5:
                        continue                               # no chair dragging over a rise
                    put("lifts", rng.choice(["cableway_cart", "cableway_cart2", "cableway_cart3"]), q[0], q[1],
                        heading(*(u * way)), rel=grip - 1.68 - ter.h(*q))
                    chairs += 1
            clear.append((pa, pb, LIFT_CLEAR))
        lifts[t.get("name", t["aerialway"])] = (cum[-1], len(sup) - 2, chairs)

    # ------------------------------------------------------------- streets: lamps, benches, bins, mailboxes
    bgrid = Points(np.array([(x, z) for _, x, z in buildings]), 75.0)

    def density(x, z, r=150.0):
        return len(bgrid.within(x, z, r))
    street = defaultdict(int)
    for ln in lines:
        if ln["group"] == "trails" or ln["family"] not in ("asf1", "asf2", "asf3") or ln.get("bridge"):
            continue
        hw = ROAD_HALF_WIDTH[ln["family"]]
        pts, cum = polyline(ln["points"])
        main = ln["highway"] in ("trunk", "trunk_link", "primary", "primary_link", "secondary")
        for k, s in enumerate(np.arange(LAMP_EVERY / 2, cum[-1], LAMP_EVERY)):
            p, d = along(pts, cum, s)
            dens = density(*p)
            if dens < DENSE:
                continue
            nrm = np.array([d[1], -d[0]]) * (1 if k % 2 == 0 else -1)
            q = p + nrm * (hw + 1.2)
            if occ.free(q[0], q[1], 0.6) and off_road(q[0], q[1], 0.6):
                put("street", "lamp_city1", q[0], q[1], heading(*(p - q)) + 90.0)   # its arm over the road
                street["street lamps"] += 1
            if main and dens >= DOWNTOWN:                  # the sidewalk, either side, wherever there's room
                for q in (p + side * (hw + off) for off in (1.6, 2.4, 3.2) for side in (-nrm, nrm)):
                    if occ.free(q[0], q[1], 0.9) and off_road(q[0], q[1], 0.8):
                        put("street", "misc_bench1", q[0], q[1], math.degrees(math.atan2(-d[1], d[0])))
                        street["benches"] += 1
                        for b in (q + d * 2.5, q - d * 2.5):
                            if occ.free(b[0], b[1], 0.5) and off_road(b[0], b[1], 0.5):
                                put("street", "garbage_bin", b[0], b[1], heading(*d))
                                street["bins"] += 1
                                break
                        break
    boxes = []
    for tpl, x, z in buildings:
        if kind_of(tpl) != "house" or density(x, z) >= DENSE or ter.h(x, z) > MAILBOX_BELOW:
            continue                                       # homes in the valleys, not the park's buildings up high
        i, dist = roads.nearest(x, z, MAILBOX_REACH * 2)
        if i is None or dist > MAILBOX_REACH:
            continue
        r = roads.xz[i]
        toward = (np.array([x, z]) - r) / (dist or 1.0)
        q = r + toward * (road_w[i] + 1.0)
        if any(np.hypot(*(q - o)) < 6.0 for o in boxes) or not occ.free(q[0], q[1], 0.4) or not off_road(q[0], q[1], 0.6):
            continue
        put("street", "misc_postbox1", q[0], q[1], heading(*(r - q)) + 90.0)      # facing the road
        boxes.append(q)
        street["mailboxes"] += 1

    # ------------------------------------------------------------- power lines
    power = defaultdict(int)

    def string_line(run):
        if len(run) < 3:
            return
        for k, p in enumerate(run):
            if k in (0, len(run) - 1):                     # end poles, their stay toward the line's end
                inward = run[1] - p if k == 0 else run[-2] - p
                put("power", "power_pole_wood5_end", p[0], p[1], heading(*inward), sink=POLE_SINK)
            else:
                put("power", "power_pole_wood5", p[0], p[1], heading(*(run[k + 1] - run[k - 1])), sink=POLE_SINK)
        for a, b in zip(run[:-1], run[1:]):
            u = (b - a) / np.hypot(*(b - a))
            side = np.array([u[1], -u[0]])
            ha, hb = ter.h(*a) - POLE_SINK + WIRE_TOP, ter.h(*b) - POLE_SINK + WIRE_TOP
            for lat, tpl in ((-1.40, "power_wire_50"), (0.0, "power_wire_50_main"), (1.40, "power_wire_50")):
                wire("power", tpl, a + side * lat, b + side * lat, ha, hb)
            clear.append((a, b, POWER_CLEAR))
        power["lines"] += 1
        power["poles"] += len(run)
        power["km"] += sum(np.hypot(*(b - a)) for a, b in zip(run[:-1], run[1:])) / 1000.0
    for ln in lines:
        if ln["group"] == "trails" or ln["family"] not in ROAD_HALF_WIDTH or ln.get("bridge"):
            continue
        hw = ROAD_HALF_WIDTH[ln["family"]]
        pts, cum = polyline(ln["points"])
        if cum[-1] < (120.0 if ln["highway"] != "residential" else 300.0):
            continue
        run = []
        for s in np.arange(10.0, cum[-1] - 10.0, POLE_EVERY):
            p, d = along(pts, cum, s)
            got = None
            if density(*p, r=120.0) >= SETTLED:
                for ds in (0.0, 3.0, -3.0, 6.0, -6.0):
                    p2, d2 = along(pts, cum, s + ds)
                    q = p2 + np.array([d2[1], -d2[0]]) * (hw + 3.0)
                    if occ.free(q[0], q[1], 0.6) and off_road(q[0], q[1], 1.5) and \
                            (not run or 25.0 < np.hypot(*(q - run[-1])) < 60.0):
                        got = q
                        break
            if got is not None and run:                    # a span whose wires would brush a rise ends the line
                ha, hb = ter.h(*run[-1]) - POLE_SINK + WIRE_TOP, ter.h(*got) - POLE_SINK + WIRE_TOP
                if lowest_gap(run[-1], got, ha, hb) < WIRE_CLEAR:
                    string_line(run)
                    run = []
            if got is None:
                string_line(run)
                run = []
            else:
                run.append(got)
        string_line(run)

    # ------------------------------------------------------------- nature
    nrng = np.random.default_rng(SEED)
    nature = defaultdict(int)
    elev = ter.elev
    # Ghost forests: dead firs, standing and fallen, in patches of the spruce-fir up high.
    ncell = int(SIZE // 40)
    field = nrng.normal(size=(ncell, ncell))
    for _ in range(3):
        field = sum(np.roll(np.roll(field, i, 0), j, 1) for i in (-1, 0, 1) for j in (-1, 0, 1)) / 9.0
    gx, gz = np.meshgrid(np.arange(GHOST_EVERY / 2, SIZE, GHOST_EVERY), np.arange(GHOST_EVERY / 2, SIZE, GHOST_EVERY))
    gx = (gx + nrng.uniform(-5, 5, gx.shape)).clip(1, SIZE - 1).ravel()
    gz = (gz + nrng.uniform(-5, 5, gz.shape)).clip(1, SIZE - 1).ravel()
    zi = (zones[(gz / zcell).astype(int).clip(0, zones.shape[0] - 1), (gx / zcell).astype(int).clip(0, zones.shape[1] - 1)])
    hi = elev[(gz / ter.cell).astype(int).clip(0, elev.shape[0] - 1), (gx / ter.cell).astype(int).clip(0, elev.shape[1] - 1)]
    pi = field[(gz // 40).astype(int).clip(0, ncell - 1), (gx // 40).astype(int).clip(0, ncell - 1)] > 0
    for x, z in zip(gx[(zi == 1) & (hi >= GHOST_FROM) & pi], gz[(zi == 1) & (hi >= GHOST_FROM) & pi]):
        if nrng.random() < 0.25:
            if occ.free(x, z, 2.0) and off_road(x, z, 3.0):
                put("nature", str(nrng.choice(FIR_LOGS)), x, z, nrng.uniform(0, 360), sink=0.15)
                nature["fallen firs"] += 1
        elif occ.free(x, z, 1.2) and off_road(x, z, 2.0):
            sc = nrng.uniform(0.8, 1.2)
            put("nature", str(nrng.choice(SNAGS)), x, z, nrng.uniform(0, 360), sc, sink=0.3 * sc)
            nature["dead firs"] += 1
    # Along the creeks: laurel thickets, mossy boulders, logs fallen across.
    for ln in water:
        if ln["class"] not in ("brook", "stream") or len(ln["points"]) < 2:
            continue
        pts, cum = polyline(ln["points"])
        on = False
        for k, s in enumerate(np.arange(0.0, cum[-1], LAUREL_EVERY)):
            if k % 8 == 0:                                 # thickets come and go every 20 m, LAUREL_SHARE of the way
                on = nrng.random() < (0.8 if on else 0.2 * LAUREL_SHARE / (1 - LAUREL_SHARE))
            if not on:
                continue
            p, d = along(pts, cum, s)
            if ZONE_NAMES[zone_at(*p)] not in ("northern", "cove", "mixed") or ter.h(*p) >= LAUREL_BELOW:
                continue
            for sgn in (1, -1):
                q = p + np.array([d[1], -d[0]]) * sgn * nrng.uniform(4.0, 10.0)
                if occ.free(q[0], q[1], 1.0) and off_road(q[0], q[1], 2.0):
                    put("nature", LAUREL, q[0], q[1], nrng.uniform(0, 360), nrng.uniform(1.4, 2.2))
                    nature["laurel"] += 1
        for s in np.arange(BOULDER_EVERY / 2, cum[-1], BOULDER_EVERY):
            if nrng.random() > BOULDER_CHANCE:
                continue
            p, d = along(pts, cum, s)
            if any(np.hypot(*(p - o)) < 12.0 for o in bridges):
                continue
            for _ in range(nrng.integers(1, 3)):
                q = p + np.array([d[1], -d[0]]) * nrng.uniform(-3.5, 3.5) + d * nrng.uniform(-3, 3)
                tpl = str(nrng.choice(BOULDERS))
                if occ.free(q[0], q[1], 1.0, 1) and off_road(q[0], q[1], 2.0):
                    sc = nrng.uniform(0.6, 1.3)
                    i = model_info(tpl)
                    put("nature", tpl, q[0], q[1], nrng.uniform(0, 360), sc, sink=0.35 * (i["max"][1] - i["min"][1]) * sc)
                    nature["creek boulders"] += 1
        for s in np.arange(nrng.uniform(50, CREEK_LOG_EVERY), cum[-1] - 20, CREEK_LOG_EVERY):
            p, d = along(pts, cum, s)
            if open_ground(*p) or any(np.hypot(*(p - o)) < 25.0 for o in bridges) or not off_road(p[0], p[1], 8.0):
                continue
            tpl = str(nrng.choice(CREEK_LOGS[ln["class"]]))
            i = model_info(tpl)
            length = i["max"][0] - i["min"][0]
            n = np.array([d[1], -d[0]])                    # the log's length (its x) across the creek
            e1, e2 = p - n * length / 2, p + n * length / 2
            if not (occ.free(*e1, 0.8, 1) and occ.free(*e2, 0.8, 1)):
                continue
            h1, h2 = ter.h(*e1), ter.h(*e2)
            put("nature", tpl, p[0], p[1], math.degrees(math.atan2(-n[1], n[0])),
                roll=math.degrees(math.atan2(h2 - h1, length)), rel=(h1 + h2) / 2 + i["center"][1] - 0.1 - ter.h(*p))
            nature["logs across creeks"] += 1

    # ------------------------------------------------------------- clear the corridors
    cells = defaultdict(list)
    for a, b, w in clear:
        lo, hi_ = np.minimum(a, b) - w, np.maximum(a, b) + w
        for i in range(int(lo[0] // 50), int(hi_[0] // 50) + 1):
            for j in range(int(lo[1] // 50), int(hi_[1] // 50) + 1):
                cells[(i, j)].append((a, b, w))

    def in_corridor(x, z):
        for a, b, w in cells.get((int(x // 50), int(z // 50)), ()):
            ab = b - a
            t = min(max(((x - a[0]) * ab[0] + (z - a[1]) * ab[1]) / (ab @ ab or 1.0), 0.0), 1.0)
            if math.hypot(x - a[0] - t * ab[0], z - a[1] - t * ab[1]) < w:
                return True
        return False
    cleared = {}
    for rel in ("forest/tb_trees.txt", "forest/tb_bushes.txt", "forest/tb_deadwood.txt", "rocks/tb_rocks.txt"):
        path = os.path.join(src, rel)
        keep, gone = [], 0
        for line in open(path):
            q = line.split(";", 3)
            if len(q) > 2 and (int((float(q[1]) - EASTING) // 50), int(float(q[2]) // 50)) in cells and \
                    in_corridor(float(q[1]) - EASTING, float(q[2])):
                gone += 1
                continue
            keep.append(line)
        if gone:
            with open(path, "w", newline="\n") as fh:
                fh.writelines(keep)
        cleared[rel] = gone

    # ------------------------------------------------------------- write
    for kind in ("markers", "signs", "props", "orchards", "footbridges", "lifts", "street", "power", "nature"):
        with open(os.path.join(out, "tb_%s.txt" % kind), "w", newline="\n") as fh:
            for tpl, x, z, yaw, pitch, roll, scale, rel in placed[kind]:
                fh.write('"%s";%.3f;%.3f;%.3f;%.3f;%.3f;%.3f;%.3f;\n' % (tpl, x + EASTING, z, yaw, pitch, roll, scale, rel))
    sheet_cols = 4
    if signs:
        thumbs = [Image.open(os.path.join(png_dir, n + "_co.png")).resize((512, 256), Image.LANCZOS) for n, *_ in signs]
        sheet = Image.new("RGB", (512 * sheet_cols, 256 * (-(-len(thumbs) // sheet_cols))), (20, 20, 20))
        for k, t in enumerate(thumbs):
            sheet.paste(t, ((k % sheet_cols) * 512, (k // sheet_cols) * 256))
        sheet.save(os.path.join(out, "signs.png"))
    count = lambda kind, pre="": sum(1 for r in placed[kind] if r[0].startswith(pre))
    summary = ["Details (tools/details.py)", "",
               "trail blazes: %d along %d named trails (%d on trees, %d on stones, %d on poles; red %d, yellow %d, "
               "green %d, blue %d)"
               % (len(placed["markers"]), len({ln.get("name") for ln in trails if ln.get("name")}),
                  count("markers", "t_"), count("markers", "stone"), count("markers", "trail_woodenpole"),
                  *(sum(1 for r in placed["markers"] if r[0].endswith(("_" + c, "_%s_summer" % c))) for c in "rygb")),
               "footbridges: %d where trails cross creeks (%s m long), models in data/footbridges"
               % (len(placed["footbridges"]), ", ".join("%d x %d" % (sum(1 for r in placed["footbridges"] if r[0] == t), n)
                                                       for n, t in bridge_tpl.items())),
               "lifts: %s" % "; ".join("%s %.0f m, %d towers, %d chairs" % (k, *v) for k, v in lifts.items()),
               "streets: %s" % ", ".join("%d %s" % (n, k) for k, n in street.items()),
               "power lines: %d lines, %.1f km, %d poles, %d wires"
               % (power["lines"], power["km"], power["poles"], count("power", "power_wire")),
               "nature: %s" % ", ".join("%d %s" % (n, k) for k, n in nature.items()),
               "cleared under lifts, bridges and power lines: %s" % ", ".join("%s %d" % kv for kv in cleared.items()),
               "trail signs: %d (%d at trailheads, %d at junctions), models in data/trailsigns"
               % (len(signs), sum(1 for s in signs if s[3].startswith("trailhead")),
                  sum(1 for s in signs if s[3] == "junction")),
               "furniture: %d pieces (%s) at %s"
               % (len(placed["props"]), ", ".join("%s %d" % (t, sum(1 for r in placed["props"] if r[0] == t)) for t in sorted({r[0] for r in placed["props"]})),
                  ", ".join("%d %s" % (n, k) for k, n in stops.items())),
               "orchards: %d trees at %d of %d homesteads and farms" % (trees, orchards, len(sites)), "", "signs:"]
    for name, title, rows, why in signs:
        summary.append("  %s  %s  [%s]  %s" % (name, title, why, "; ".join(
            "%s%s %.1f" % ({"left": "<- ", "right": "-> ", "ahead": "^ "}.get(w, ""), pl, mi) for w, pl, mi in rows)))
    with open(os.path.join(out, "summary.txt"), "w", newline="\n", encoding="utf-8") as fh:
        fh.write("\n".join(summary) + "\n")
    print("\n".join(summary[:summary.index("signs:")]))


if __name__ == "__main__":
    main()
