"""Convert every .paa in a folder to .png with DayZ Tools' ImageToPAA, in parallel.

    python tools/paa_to_png.py <ImageToPAA.exe> <paa folder> <png folder>
"""

import concurrent.futures
import glob
import os
import subprocess
import sys


def convert(exe, src, dst):
    if os.path.isfile(dst):
        return None
    run = subprocess.run([exe, src, dst], capture_output=True, text=True, errors="replace", timeout=120)
    if not os.path.isfile(dst):
        return "%s: exit %s %s" % (os.path.basename(src), run.returncode, (run.stdout + run.stderr).strip()[-200:])
    return None


def main():
    exe, src_dir, out_dir = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(src_dir, "*.paa")))
    jobs = [(f, os.path.join(out_dir, os.path.splitext(os.path.basename(f))[0] + ".png")) for f in files]
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 2)) as pool:
        for i, err in enumerate(pool.map(lambda j: convert(exe, *j), jobs), 1):
            if err:
                failed.append(err)
            if i % 250 == 0:
                print("%d / %d" % (i, len(jobs)), flush=True)
    print("done: %d converted, %d failed" % (len(jobs) - len(failed), len(failed)))
    for f in failed:
        print("  " + f)


if __name__ == "__main__":
    main()
