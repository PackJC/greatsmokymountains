"""Write the map's place names (CfgWorlds >> greatsmokymountains >> Names) and its
centre position into config.cpp, from the OSM places the mission uses.

    python tools/names.py source/mission/osm_places.json source/buildings/elevation.npy tools/georef.json config.cpp
        [--water source/details/tb_props.txt]

The classes follow vanilla Chernarus (DZ\\worlds\\chernarusplus\\world\\config.bin):
name, position[] (x, z) and one of DayZ's own types:
  Capital    place=city
  City       place=town
  Village    place=village, hamlet
  Local      LeConte Lodge (tourism=alpine_hut), ranger stations, Newfound Gap
  Camp       campgrounds and backcountry campsites (tourism=camp_site)
  Hill       named peaks, one per name (the highest)
  ViewPoint  named overlooks (tourism=viewpoint)
  Waterspring, Waterpump, Fountain   with --water: an icon (no name) at each of
             tools/details.py's springs, hand pumps and fountains
Places sharing a name become one label: the highest-ranked type, placed at the
node (a way's or relation's centre is only its bounding-box centre), or the
highest one for peaks. A label within 150 m of a higher-ranked one is dropped.
centerPosition[] becomes the map's middle at ground height. Rerunning replaces
both; the rest of config.cpp is left as it is.
"""

import argparse
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import bilinear  # noqa: E402
from geo import utm  # noqa: E402

SIZE = 20480.0
TYPES = ["Capital", "City", "Village", "Local", "Camp", "Hill", "ViewPoint"]   # by rank
PREFIX = {"Capital": "Settlement", "City": "Settlement", "Village": "Settlement"}
PLACES = {"city": "Capital", "town": "City", "village": "Village", "hamlet": "Village"}
GAPS = ("Newfound Gap",)                     # saddles given a Local label
NEAR = 150.0                                 # drop a label this close to a higher-ranked one
EASTING = 200000.0
# Water from tools/details.py, shown with the game's own map icons (CfgLocationTypes).
WATER = [("waterspring_", "Waterspring"), ("misc_well_pump_", "Waterpump"), ("misc_fountain", "Fountain")]


def type_of(t):
    if t.get("place") in PLACES:
        return PLACES[t["place"]]
    if t.get("natural") == "peak":
        return "Hill"
    if t.get("natural") == "saddle" and t.get("name") in GAPS:
        return "Local"
    if t.get("tourism") == "alpine_hut" or t.get("amenity") == "ranger_station":
        return "Local"
    if t.get("tourism") == "camp_site":
        return "Camp"
    if t.get("tourism") == "viewpoint":
        return "ViewPoint"
    return None


def places(osm, geo, ground):
    """OSM elements -> candidates (type, name, x, z, is_node, height)."""
    out = []
    for e in json.load(open(osm, encoding="utf-8"))["elements"]:
        p = e.get("center") or ({"lat": e["lat"], "lon": e["lon"]} if "lat" in e else None)
        t = e.get("tags", {})
        kind = type_of(t)
        if not p or not kind or not t.get("name"):
            continue
        x, z = utm(p["lat"], p["lon"], 17)
        x, z = x + geo["offset_x"], z + geo["offset_y"]
        if not (0 <= x <= SIZE and 0 <= z <= SIZE):
            continue
        try:
            h = float(t["ele"])
        except (KeyError, ValueError):
            h = ground(x, z)
        out.append((kind, t["name"].strip(), x, z, e["type"] == "node", h))
    return out


def labels(cands):
    """One label per name, then drop those crowding a higher-ranked label."""
    groups = {}
    for c in cands:
        groups.setdefault(c[1].split(" - ")[0].casefold(), []).append(c)
    merged = []
    for g in groups.values():
        kind = min((c[0] for c in g), key=TYPES.index)
        at = max(g, key=lambda c: (c[4], c[5]) if kind != "Hill" else (c[0] == "Hill", c[5]))
        name = min((c[1] for c in g), key=len)
        merged.append((kind, name, at[2], at[3]))
    merged.sort(key=lambda m: (TYPES.index(m[0]), m[1]))
    kept = []
    for m in merged:
        if all(np.hypot(m[2] - k[2], m[3] - k[3]) >= NEAR for k in kept):
            kept.append(m)
    return kept


def block(kept, nl):
    out, used = ["\t\tclass Names", "\t\t{"], set()
    for kind, name, x, z in kept:
        cls = PREFIX.get(kind, kind) + "_" + "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", name))
        cls = cls.rstrip("_")                          # the water icons have no name
        base, n = cls, 2
        while cls in used:
            cls, n = f"{base}_{n}", n + 1
        used.add(cls)
        out += [f"\t\t\tclass {cls}", "\t\t\t{",
                '\t\t\t\tname="{}";'.format(name.replace('"', '""')),
                f"\t\t\t\tposition[]={{{x:.1f},{z:.1f}}};",
                f'\t\t\t\ttype="{kind}";',
                "\t\t\t};"]
    out.append("\t\t};")
    return nl.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("osm")
    ap.add_argument("elevation")
    ap.add_argument("georef")
    ap.add_argument("config")
    ap.add_argument("--water", help="tools/details.py's tb_props.txt: springs, pumps and fountains get map icons")
    a = ap.parse_args()

    elev = np.load(a.elevation)
    cell = SIZE / elev.shape[0]
    ground = lambda x, z: bilinear(elev, x / cell, z / cell)  # noqa: E731
    geo = json.load(open(a.georef))
    kept = labels(places(a.osm, geo, ground))
    water = []
    if a.water:
        for line in open(a.water):
            p = line.strip().rstrip(";").split(";")
            kind = next((k for pre, k in WATER if p[0].strip('"').startswith(pre)), None)
            if kind:
                water.append((kind, "", float(p[1]) - EASTING, float(p[2])))
    kept += water

    text = open(a.config, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in text else "\n"
    world = text.index("\tclass greatsmokymountains: ChernarusPlus")
    names = re.compile(r"\t\tclass Names\r?\n\t\t\{\r?\n.*?^\t\t\};", re.S | re.M)
    m = names.search(text, world)
    text = text[:m.start()] + block(kept, nl) + text[m.end():]
    c = SIZE / 2
    centre = f"centerPosition[]={{{c:g},{c:g},{ground(c, c):.1f}}};"
    text, n = re.subn(r"centerPosition\[\]=\{[^}]*\};", centre, text, count=1)
    assert n == 1
    open(a.config, "w", encoding="utf-8", newline="").write(text)

    for kind in TYPES:
        sel = [k[1] for k in kept if k[0] == kind]
        print(f"{kind:9} {len(sel):3}  {', '.join(sel)}")
    for kind in sorted({w[0] for w in water}):
        print(f"{kind:11} {sum(1 for w in water if w[0] == kind):3} map icons")
    print(f"{len(kept)} names; {centre}")


if __name__ == "__main__":
    main()
