"""Copies the bundled sources (src/<name>) into ./<name>. Existing code is overwritten; models, env and user data are kept."""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KEEP = {"env", "uploads", "last_workspace.json", ".install_ok", ".thumbnails"}

name = sys.argv[1]
src = os.path.join(HERE, "src", name)
dst = os.path.join(HERE, name)
if not os.path.isdir(src):
    sys.exit(f"ERROR: bundled sources not found: {src}. Make sure the src/ folder is in the repository.")


def copy(s, d, top=False):
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(s):
        if top and f in KEEP:
            continue
        sp, dp = os.path.join(s, f), os.path.join(d, f)
        if os.path.isdir(sp):
            if f == "model_assets" and os.path.islink(dp):
                continue
            if f == "model_assets" and top and os.path.isdir(dp) and os.path.realpath(dp) != dp:
                continue
            copy(sp, dp)
        else:
            if top and f == "model_assets":
                continue
            shutil.copy2(sp, dp)


copy(src, dst, top=True)
# Webui: make sure the old Qt interface is not left behind from an earlier copy
if name == "webui":
    for p in ("app/ui", "app/processors/video_processor.py"):
        full = os.path.join(dst, p)
        if os.path.isdir(full):
            shutil.rmtree(full)
        elif os.path.isfile(full):
            os.remove(full)
print(f"{name}: sources copied")
