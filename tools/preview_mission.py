"""Draw where the server mission spawns things, over the satellite preview.

    python tools/preview_mission.py <mission folder> <satellite_preview.png> <out folder>

Writes preview_spawns.png (players, vehicles, heli crashes, supply crates, police
wrecks, military convoys, police scenes, bonfires) and preview_wildlife.png (animal
territories and infected zones),
read straight from the mission's XML files.
"""

import os
import sys
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageEnhance

SIZE = 20480.0


def main():
    mission, sat, out = sys.argv[1:4]
    base = Image.open(sat).convert("RGB")
    base = ImageEnhance.Brightness(ImageEnhance.Color(base).enhance(0.5)).enhance(0.75)
    px = base.size[0] / SIZE

    def xy(x, z):
        return x * px, (SIZE - z) * px

    def dot(d, x, z, r, fill, outline=(0, 0, 0)):
        u, v = xy(x, z)
        d.ellipse((u - r, v - r, u + r, v + r), fill=fill, outline=outline)

    def legend(d, items):
        y = 12
        d.rectangle((8, 8, 330, 16 + 22 * len(items)), fill=(255, 255, 255))
        for label, colour in items:
            d.ellipse((16, y + 3, 30, y + 17), fill=colour, outline=(0, 0, 0))
            d.text((38, y + 4), label, fill=(0, 0, 0))
            y += 22

    # Spawns.
    img = base.copy()
    d = ImageDraw.Draw(img)
    sp = ET.parse(os.path.join(mission, "cfgplayerspawnpoints.xml")).getroot()
    for section, colour, r in (("hop", (150, 255, 150), 9), ("fresh", (40, 200, 40), 6)):
        for p in sp.find(section).iter("pos"):
            dot(d, float(p.get("x")), float(p.get("z")), r, colour)
    styles = {"Vehicle": ((60, 140, 255), 5, "vehicles"), "StaticHeliCrash": ((255, 40, 40), 9, "heli crashes"),
              "StaticAirplaneCrate": ((255, 160, 0), 7, "supply crates"),
              "StaticPoliceCar": ((255, 255, 255), 4, "police car wrecks"),
              "StaticMilitaryConvoy": ((120, 140, 50), 10, "military convoys"),
              "StaticPoliceSituation": ((40, 70, 230), 8, "roadblocks, crashes, abandoned cars"),
              "StaticBonfire": ((255, 230, 0), 4, "bonfires")}
    counts = {}
    for e in ET.parse(os.path.join(mission, "cfgeventspawns.xml")).getroot().iter("event"):
        key = next((k for k in styles if e.get("name").startswith(k)), None)
        if not key:
            continue
        colour, r, label = styles[key]
        for p in e.iter("pos"):
            dot(d, float(p.get("x")), float(p.get("z")), r, colour)
            counts[label] = counts.get(label, 0) + 1
    legend(d, [("fresh spawns", (40, 200, 40)), ("hop / travel spawns", (150, 255, 150))]
           + [("%s (%d)" % (label, counts.get(label, 0)), colour) for colour, r, label in styles.values()])
    img.save(os.path.join(out, "preview_spawns.png"))

    # Wildlife and infected.
    img = base.copy()
    d = ImageDraw.Draw(img, "RGBA")
    files = [("zombie_territories.xml", (200, 60, 255, 110), "infected"),
             ("bear_territories.xml", (140, 80, 20, 150), "bears"),
             ("red_deer_territories.xml", (255, 120, 60, 130), "red deer"),
             ("roe_deer_territories.xml", (255, 200, 60, 130), "roe deer"),
             ("wild_boar_territories.xml", (230, 40, 120, 130), "wild boar"),
             ("wolf_territories.xml", (200, 200, 200, 110), "wolves"),
             ("cattle_territories.xml", (60, 220, 255, 150), "cattle"),
             ("sheep_goat_territories.xml", (255, 255, 255, 150), "sheep and goats"),
             ("pig_territories.xml", (255, 150, 200, 150), "pigs")]
    items = []
    for f, colour, label in files:
        zones = list(ET.parse(os.path.join(mission, "env", f)).getroot().iter("zone"))
        for z in zones:
            u, v = xy(float(z.get("x")), float(z.get("z")))
            r = float(z.get("r")) * px
            d.ellipse((u - r, v - r, u + r, v + r), fill=colour)
        items.append(("%s (%d zones)" % (label, len(zones)), colour[:3]))
    legend(d, items)
    img.save(os.path.join(out, "preview_wildlife.png"))
    print("wrote preview_spawns.png and preview_wildlife.png")


if __name__ == "__main__":
    main()
