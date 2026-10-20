"""Read OpenStreetMap's roads and hiking trails into lines for the rest of the tools.

    python tools/osm_roads.py <overpass highways.json> <world wrp, unused> tools/georef.json source/roads

<overpass highways.json> is an Overpass API answer ("out tags geom") holding the
map area's highway ways and hiking route relations. Writes into <out>:
  roads.shp/.shx/.dbf    every road and trail as a polyline, in Terrain Builder
                         coordinates, for a shapes layer
  lines.json             the same lines in map coordinates, with their part family,
                         for tools/road_build.py (which lays the parts and carves
                         the ground), tools/paint_roads.py and the others
  summary.txt            lengths, bridges and named trails

Each way gets a part family by its class and surface (FAMILIES: asf1 to mud, or
trail). chain() here lays straight pieces end to end along a line; the water
and the trails still use it, the roads use tools/road_build.py's curves.
"""

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import utm  # noqa: E402
from shapefile import write_polylines  # noqa: E402

SIZE = 20480.0
EASTING = 200000.0
EDGE = 2.0                       # keep lines this far inside the map

# Road part families: piece lengths (longest first) -> template name, part width,
# bend tolerance (how far the line may stray from a piece before a shorter one is used).
FAMILIES = {
    "asf1": ({25.0: "asf1_25", 12.5: "asf1_12", 6.25: "asf1_6"}, 12.0, 0.35),
    "asf2": ({25.0: "asf2_25", 12.5: "asf2_12", 6.25: "asf2_6"}, 9.0, 0.35),
    "asf3": ({25.0: "asf3_25", 12.5: "asf3_12", 6.25: "asf3_6"}, 7.0, 0.4),
    "grav": ({25.0: "grav_25", 12.5: "grav_12", 6.25: "grav_6"}, 6.0, 0.5),
    "mud": ({25.0: "mud_25", 12.5: "mud_12", 6.25: "mud_6"}, 5.0, 0.6),
    "trail": ({10.0: "path_dirt_10"}, 2.35, None),
}
BRIDGE_MAX = 150.0               # bridges up to this long get a bridge model (tools/buildings.py), not road parts

UNPAVED = {"gravel", "fine_gravel", "compacted", "unpaved", "dirt", "ground", "earth", "mud", "sand", "grass"}
SKIP = {"proposed", "construction", "raceway", "steps", "pedestrian", "cycleway", "service", "elevator",
        "corridor", "platform", "bus_stop", "rest_area", "services", "abandoned", "razed", "no"}


def classify(tags, in_hiking_route):
    """(family, group) for a highway way, or None to leave it out."""
    h = tags.get("highway", "")
    name = tags.get("name", "").lower()
    surface = tags.get("surface", "")
    if h in SKIP:
        return None
    if h in ("motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"):
        try:
            lanes = int(tags.get("lanes", "2").split(";")[0])
        except ValueError:
            lanes = 2
        return ("asf1" if lanes >= 4 else "asf2"), "main"
    if h in ("secondary", "tertiary", "secondary_link", "tertiary_link", "unclassified"):
        return ("grav" if surface in UNPAVED else "asf3"), "main"
    if h in ("residential", "living_street", "road"):
        return ("grav" if surface in UNPAVED else "asf3"), "local"
    if h == "track":
        return ("grav" if surface in ("gravel", "fine_gravel", "compacted") else "mud"), "local"
    if h in ("path", "bridleway"):
        return "trail", "trails"
    if h == "footway" and (in_hiking_route or "trail" in name or "walkway" in name):
        return "trail", "trails"
    return None


def inside_runs(points):
    """Split a polyline into the runs of points that lie inside the map."""
    runs, cur = [], []
    for p in points:
        if EDGE <= p[0] <= SIZE - EDGE and EDGE <= p[1] <= SIZE - EDGE:
            cur.append(p)
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def next_at_distance(pts, p, seg, t0, dist):
    """First point after (seg, t0) along the polyline at straight-line distance `dist`
    from p. Returns (point, seg, t) or None when the line ends first."""
    for s in range(seg, len(pts) - 1):
        a, b = pts[s], pts[s + 1]
        d = b - a
        f = a - p
        qa = d @ d
        if qa < 1e-12:
            continue
        qb = 2 * (f @ d)
        qc = f @ f - dist * dist
        disc = qb * qb - 4 * qa * qc
        if disc < 0:
            continue
        root = math.sqrt(disc)
        for t in sorted(((-qb - root) / (2 * qa), (-qb + root) / (2 * qa))):
            lo = t0 + 1e-9 if s == seg else 0.0
            if lo <= t <= 1.0:
                return a + t * d, s, t
    return None


def deviation(pts, p, seg, q, qseg):
    """Largest distance of the polyline's corners between p and q from the chord p-q."""
    chord = q - p
    n = math.hypot(chord[0], chord[1])
    if n < 1e-9 or qseg <= seg:
        return 0.0
    corners = pts[seg + 1:qseg + 1]
    return float(np.abs((corners[:, 0] - p[0]) * chord[1] - (corners[:, 1] - p[1]) * chord[0]).max() / n)


def chain(line, pieces, tol):
    """Chain straight pieces end to end along a polyline. Returns [(start, end, length)]."""
    pts = np.asarray(line, float)
    lengths = sorted(pieces, reverse=True)
    out, p, seg, t = [], pts[0], 0, 0.0
    while True:
        placed = None
        for k, length in enumerate(lengths):
            nxt = next_at_distance(pts, p, seg, t, length)
            if nxt is None:
                continue
            q, qseg, qt = nxt
            if tol is None or k == len(lengths) - 1 or deviation(pts, p, seg, q, qseg) <= tol:
                placed = (q, qseg, qt, length)
                break
        if placed is None:
            break
        q, seg, t, length = placed
        out.append((p, q, length))
        p = q
    # Cover the leftover tail with the shortest piece, ending exactly at the line's end.
    end = pts[-1]
    rest = math.hypot(*(end - p))
    shortest = lengths[-1]
    if rest > 0.15 * shortest:
        direction = (end - p) / rest
        out.append((end - direction * shortest, end, shortest))
    return out


def main():
    osm_path, wrp_path, georef_path, out = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    geo = json.load(open(georef_path))
    ox, oy = geo["offset_x"], geo["offset_y"]

    elements = json.load(open(osm_path, encoding="utf-8"))["elements"]
    hiking = set()
    for e in elements:
        if e["type"] == "relation":
            hiking.update(m["ref"] for m in e.get("members", []) if m["type"] == "way")

    lines = []                        # dicts: points (map coords), family, group, tags
    for e in elements:
        if e["type"] != "way" or "geometry" not in e:
            continue
        cls = classify(e["tags"], e["id"] in hiking)
        if cls is None:
            continue
        pts = []
        for node in e["geometry"]:
            x, y = utm(node["lat"], node["lon"], 17)
            pts.append((x + ox, y + oy))
        for run in inside_runs(pts):
            lines.append({"points": run, "family": cls[0], "group": cls[1], "id": e["id"],
                          "highway": e["tags"].get("highway", ""), "name": e["tags"].get("name", ""),
                          "bridge": e["tags"].get("bridge", "") not in ("", "no")})

    # Lengths (the parts themselves are tools/road_build.py's).
    metres, bridged = {}, 0
    for ln in lines:
        span = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(ln["points"], ln["points"][1:]))
        metres[ln["family"]] = metres.get(ln["family"], 0.0) + span
        if ln["bridge"] and span <= BRIDGE_MAX:
            bridged += 1                         # a bridge model carries the road here

    # Shapes for Terrain Builder, in its coordinates (easting + 200000).
    write_polylines(
        os.path.join(out, "roads"),
        [[(x + EASTING, y) for x, y in ln["points"]] for ln in lines],
        [("FAMILY", "C", 8, 0), ("GROUP", "C", 8, 0), ("HIGHWAY", "C", 16, 0), ("NAME", "C", 60, 0),
         ("WIDTH", "N", 6, 2), ("BRIDGE", "N", 1, 0), ("OSM_ID", "N", 12, 0)],
        [(ln["family"], ln["group"], ln["highway"], ln["name"], FAMILIES[ln["family"]][1],
          1 if ln["bridge"] else 0, ln["id"]) for ln in lines])

    with open(os.path.join(out, "lines.json"), "w") as fh:
        json.dump([{k: v for k, v in ln.items()} for ln in lines], fh)

    names = {}
    for ln in lines:
        if ln["family"] == "trail" and ln["name"]:
            names[ln["name"]] = names.get(ln["name"], 0.0) + sum(
                math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(ln["points"], ln["points"][1:]))
    with open(os.path.join(out, "summary.txt"), "w", newline="\n") as fh:
        fh.write("Roads and trails from OpenStreetMap (c) OpenStreetMap contributors, ODbL.\n")
        fh.write("Placed with tools/georef.json: map = UTM 17N + (%.2f, %.2f).\n\n" % (ox, oy))
        fh.write("length by part family:\n")
        for fam in FAMILIES:
            fh.write("  %-6s %7.1f km\n" % (fam, metres.get(fam, 0) / 1000))
        fh.write("\nbridges: %d spans up to %g m left to bridge models (tools/buildings.py); %d longer ones keep road parts\n"
                 % (bridged, BRIDGE_MAX, len([ln for ln in lines if ln["bridge"]]) - bridged))
        fh.write("\nnamed trails:\n")
        for n, m in sorted(names.items(), key=lambda kv: -kv[1]):
            fh.write("  %6.1f km  %s\n" % (m / 1000, n))
    print(open(os.path.join(out, "summary.txt")).read())


if __name__ == "__main__":
    main()
