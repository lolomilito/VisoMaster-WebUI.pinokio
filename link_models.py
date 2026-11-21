"""
Shares the model_assets folder between VisoMaster (desktop) and VisoMaster WebUI.

Usage:  python link_models.py desktop
        python link_models.py webui

- Moves the contents of <app>/model_assets to shared/model_assets (nothing is overwritten).
- Replaces <app>/model_assets with a link (junction on Windows, symlink elsewhere)
  to shared/model_assets.
- If a file exists in both places with a different size, the shared one is kept and
  the other is stored in shared/_conflicts/<app>/ (nothing is deleted).
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.join(ROOT, "shared", "model_assets")


def merge(src, dst, conflicts_dir, rel=""):
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s) and not os.path.islink(s):
            if os.path.exists(d) and not os.path.isdir(d):
                cdir = os.path.join(conflicts_dir, rel)
                os.makedirs(cdir, exist_ok=True)
                shutil.move(s, os.path.join(cdir, name))
            else:
                merge(s, d, conflicts_dir, os.path.join(rel, name))
        elif not os.path.exists(d):
            shutil.move(s, d)
        elif os.path.isfile(d) and os.path.getsize(s) == os.path.getsize(d):
            os.remove(s)  # duplicate: keep the shared one
        else:
            cdir = os.path.join(conflicts_dir, rel)
            os.makedirs(cdir, exist_ok=True)
            shutil.move(s, os.path.join(cdir, name))
            print(f"WARNING: {os.path.join(rel, name)} differs from the shared one; saved in _conflicts")


def make_link(target):
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", target, SHARED], check=True)
    else:
        os.symlink(SHARED, target, target_is_directory=True)


def link(app):
    app_dir = os.path.join(ROOT, app)
    if not os.path.isdir(app_dir):
        print(f"[{app}] is not installed, skipping.")
        return
    target = os.path.join(app_dir, "model_assets")
    os.makedirs(SHARED, exist_ok=True)

    if os.path.exists(target) and os.path.realpath(target) == os.path.realpath(SHARED):
        print(f"[{app}] model_assets is already linked to shared.")
        return

    if os.path.isdir(target):
        conflicts = os.path.join(ROOT, "shared", "_conflicts", app)
        print(f"[{app}] moving model_assets to shared...")
        merge(target, SHARED, conflicts)
        shutil.rmtree(target)

    make_link(target)
    print(f"[{app}] model_assets -> {SHARED}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python link_models.py <desktop|webui>")
        sys.exit(1)
    for a in sys.argv[1:]:
        link(a)
