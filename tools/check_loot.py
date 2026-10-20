"""Check where every item type in the mission's economy can spawn, by tier.

    python tools/check_loot.py <mission folder>

An item can spawn at a loot point when one of its usages is the point's (its
building's or wreck's usages from mapgroupproto.xml, plus the usages painted on
areaflags.map where it stands), its category is one of the point's containers',
and the point's tier (areaflags.map) is one of the item's. Loot points are every
placed building (mapgrouppos.xml) and every active event's wreck or crate,
including the children of event groups (cfgeventgroups.xml).

Vanilla's own map checks out the same way, with no item left over except 85 rusty
car parts (category lootdispatch), which the economy hands out some other way
and which spawn in no building on any map; they're listed apart.
"""

import os
import struct
import sys
import xml.etree.ElementTree as ET

USAGE = ["Military", "Police", "Medic", "Firefighter", "Industrial", "Farm", "Coast", "Town", "Village", "Hunting",
         "Office", "School", "Prison", "Lunapark", "SeasonalEvent", "ContaminatedArea", "Historical"]
NOT_BUILDING_LOOT = ("lootdispatch",)


def read_flags(path):
    """areaflags.map -> (cell size, usage bits, value bits), rows from the south."""
    import numpy as np
    with open(path, "rb") as fh:
        nx, nz, sx, sz = struct.unpack("<6i", fh.read(24))[:4]
        usage = np.frombuffer(fh.read(nx * nz * 4), np.uint32).reshape(nz, nx)
        value = np.frombuffer(fh.read(nx * nz), np.uint8).reshape(nz, nx)
    return sx / nx, usage, value


def reach(mission):
    """Item type -> {"building": tiers, "event": tiers, "nominal", "category", "usage"} (tiers 0-3)."""
    cell, usage, value = read_flags(os.path.join(mission, "areaflags.map"))
    n = usage.shape[0]

    def at(x, z):
        i, j = min(max(int(z / cell), 0), n - 1), min(max(int(x / cell), 0), n - 1)
        u, v = int(usage[i, j]), int(value[i, j])
        return {name for b, name in enumerate(USAGE) if u >> b & 1}, {k for k in range(4) if v >> k & 1}
    proto = {g.get("name"): ({u.get("name") for u in g.findall("usage")}, {c.get("name") for c in g.iter("category")})
             for g in ET.parse(os.path.join(mission, "mapgroupproto.xml")).getroot().iter("group")}
    slots = ({}, {})                             # (usage, category) -> tiers: buildings, events

    def add(which, name, x, z):
        if name not in proto:
            return
        us, cats = proto[name]
        area, tiers = at(x, z)
        for u in us | area:
            for c in cats:
                slots[which].setdefault((u, c), set()).update(tiers)
    for g in ET.parse(os.path.join(mission, "mapgrouppos.xml")).getroot().iter("group"):
        x, _, z = (float(v) for v in g.get("pos").split())
        add(0, g.get("name"), x, z)
    groups = {}
    path = os.path.join(mission, "cfgeventgroups.xml")
    if os.path.isfile(path):
        groups = {g.get("name"): [(c.get("type"), float(c.get("x", 0)), float(c.get("z", 0))) for c in g.iter("child")]
                  for g in ET.parse(path).getroot().iter("group")}
    active = {e.get("name"): [c.get("type") for c in e.iter("child")]
              for e in ET.parse(os.path.join(mission, "db", "events.xml")).getroot().iter("event")
              if e.findtext("active", "0") == "1" and int(e.findtext("nominal", "0")) > 0}
    for e in ET.parse(os.path.join(mission, "cfgeventspawns.xml")).getroot().iter("event"):
        if e.get("name") not in active:
            continue
        for p in e.iter("pos"):
            x, z = float(p.get("x")), float(p.get("z"))
            for t, dx, dz in groups.get(p.get("group"), []):
                add(1, t, x + dx, z + dz)
            for child in active[e.get("name")]:
                add(1, child, x, z)
    out = {}
    for t in ET.parse(os.path.join(mission, "db", "types.xml")).getroot().iter("type"):
        nominal = int(t.findtext("nominal", "0"))
        us = [u.get("name") for u in t.iter("usage")]
        if nominal <= 0 or not us:
            continue
        tiers = {int(v.get("name")[4:]) - 1 for v in t.iter("value") if (v.get("name") or "").startswith("Tier")}
        tiers = tiers or {0, 1, 2, 3}
        cat = t.find("category").get("name") if t.find("category") is not None else None
        got = []
        for s in slots:
            ts = set()
            for (su, sc), v in s.items():
                if su in us and (cat is None or sc == cat):
                    ts |= v
            got.append(ts & tiers)
        out[t.get("name")] = {"building": got[0], "event": got[1], "nominal": nominal, "category": cat, "usage": us,
                              "tiers": tiers}
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    items = reach(sys.argv[1])
    print("item types that can spawn, tiers 1-4:",
          " / ".join(str(sum(1 for i in items.values() if k in i["building"] | i["event"])) for k in range(4)))
    print("  of them only at event wrecks and crates:",
          " / ".join(str(sum(1 for i in items.values() if k in i["event"] and k not in i["building"])) for k in range(4)))
    never = {n: i for n, i in items.items() if not (i["building"] | i["event"])}
    apart = sorted(n for n, i in never.items() if i["category"] in NOT_BUILDING_LOOT)
    left = sorted((n for n in never if n not in apart), key=lambda n: (never[n]["usage"], n))
    print("never spawn: %d (and %d car parts, category lootdispatch, as on every map)" % (len(left), len(apart)))
    for n in left:
        i = never[n]
        print("  %-28s %-12s %-28s tiers %s" % (n, i["category"], ",".join(i["usage"]),
                                               "".join(str(k + 1) for k in sorted(i["tiers"]))))
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
