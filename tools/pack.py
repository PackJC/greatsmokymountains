"""Build and sign the mod's one PBO, greatsmokymountains.pbo.

    python tools/pack.py <mod Addons folder> [--no-sign]

It holds the config, the world (binarized), the textures and scenes, the world's
CE data (ce, copied from the server mission by tools/stage_ce.py first) and the
AI navmesh (navmesh\\navmesh.nm, once it's been generated); the last two are
packed as they are (tools/include.txt).

Binarize reads every config.cpp under its project folder, so one broken
work-in-progress mod on P: stops every build. The map is therefore built
from %TEMP%\\gsm_project, a folder of junctions to the vanilla game data (bin,
Core, DZ, graphics, gui, languagecore, scripts, system) and this map only;
the script makes it if it's missing (in %TEMP%, so nothing is added beside the
projects on P:). Junctions are links: never delete it recursively (remove
each link with rmdir).

The PBO is signed with DayZ Tools\\Bin\\DsUtils\\Geb.biprivatekey; the mod's
Keys\\Geb.bikey verifies it.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage_ce import stage  # noqa: E402

TOOLS = r"G:\SteamLibrary\steamapps\common\DayZ Tools\Bin"
AB = os.path.join(TOOLS, "AddonBuilder", "AddonBuilder.exe")
SIGN = os.path.join(TOOLS, "DsUtils", "DSSignFile.exe")
KEY = os.path.join(TOOLS, "DsUtils", "Geb.biprivatekey")
P = "P:\\"
MAP = os.path.join(P, "greatsmokymountains")
PROJECT = os.path.join(os.environ["TEMP"], "gsm_project")
LINKS = ["bin", "Core", "DZ", "graphics", "gui", "languagecore", "scripts", "system", "greatsmokymountains"]
HERE = os.path.dirname(os.path.abspath(__file__))
OLD_PBOS = ["greatsmokymountains_ce.pbo", "greatsmokymountains_navmesh.pbo"]   # from when there were three


def ensure_project():
    os.makedirs(PROJECT, exist_ok=True)
    for name in LINKS:
        link = os.path.join(PROJECT, name)
        if not os.path.exists(link):
            subprocess.run(["cmd", "/c", "mklink", "/J", link, os.path.join(P, name)], check=True,
                           capture_output=True)


def addon_builder(args, log):
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        run = subprocess.run([AB] + args, stdout=fh, stderr=subprocess.STDOUT)
    text = open(log, encoding="utf-8", errors="replace").read()
    if "Build Successful" not in text:
        tail = [l for l in text.splitlines() if "Updating base class" not in l][-40:]
        print("\n".join(tail))
        sys.exit("Addon Builder failed (exit %s); log: %s" % (run.returncode, log))


def sign(pbo):
    for old in os.listdir(os.path.dirname(pbo)):
        if old.lower().startswith(os.path.basename(pbo).lower() + ".") and old.lower().endswith(".bisign"):
            os.remove(os.path.join(os.path.dirname(pbo), old))
    subprocess.run([SIGN, KEY, pbo], check=True, capture_output=True)
    print("  signed", os.path.basename(pbo))


def main():
    out = os.path.abspath(sys.argv[1])
    flags = set(sys.argv[2:])
    logs = os.path.join(os.environ["TEMP"], "gsm_pack_logs")
    os.makedirs(logs, exist_ok=True)
    old = [f for f in OLD_PBOS if os.path.exists(os.path.join(out, f))]
    if old:
        sys.exit("%s in %s: the mod is one PBO now and these would load the same files twice. "
                 "Delete them (and their .bisign) first." % (", ".join(old), out))
    n = stage(os.path.join(MAP, "mission", "dayzOffline.greatsmokymountains"), os.path.join(MAP, "ce"))
    print("ce: %d mission files copied into %s" % (n, os.path.join(MAP, "ce")), flush=True)
    nav = os.path.join(MAP, "navmesh")
    if not os.path.isfile(os.path.join(nav, "navmesh.nm")):
        print("no navmesh\\navmesh.nm yet: packing without it, so the AI will stand still "
              "(README, 'The AI navmesh')", flush=True)
    elif [f for f in os.listdir(nav) if f.lower() != "navmesh.nm"]:
        sys.exit("only navmesh.nm may be in %s" % nav)
    ensure_project()
    print("map: binarizing and packing (about half an hour)...", flush=True)
    addon_builder([os.path.join(PROJECT, "greatsmokymountains"), out, "-clear", "-prefix=greatsmokymountains",
                   "-project=" + PROJECT, "-include=" + os.path.join(HERE, "include.txt")],
                  os.path.join(logs, "map.log"))
    pbo = os.path.join(out, "greatsmokymountains.pbo")
    if "--no-sign" not in flags:
        sign(pbo)
        keys = os.path.join(os.path.dirname(out), "Keys")
        if os.path.isdir(keys):
            run = subprocess.run([os.path.join(TOOLS, "DsUtils", "DSCheckSignatures.exe"), out, keys],
                                 capture_output=True, text=True, errors="replace")
            bad = [l for l in run.stdout.splitlines() if l.startswith("Signature") and not l.endswith("is OK")]
            if run.returncode or bad:
                print(run.stdout)
                sys.exit("signature check failed against %s" % keys)
            print("  signature checks out against", keys)
    print("%-34s %8.1f MB" % (os.path.basename(pbo), os.path.getsize(pbo) / 1e6))
    subprocess.run([sys.executable, os.path.join(HERE, "check_pbo.py"), pbo], check=True)


if __name__ == "__main__":
    main()
