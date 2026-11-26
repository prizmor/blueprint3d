#!/bin/sh
# Blueprint3D setup for Linux and macOS: creates venv/ in the repository root (Python 3.12, build123d/OpenCascade,
# numpy, scipy) and checks that Blender and a headless browser can be found.
#   sh scripts/install.sh
# Python: uv is used when found (BP3D_UV or PATH) and installs Python 3.12 into .python/ by itself;
# otherwise python3.12 / python3 (3.10-3.13) from PATH is used.
set -eu
REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VENV="$REPO/venv"
PY="$VENV/bin/python"
REQ="$REPO/requirements.txt"

# 1. Bodies are stored in Git LFS: a clone without LFS has text pointers instead of .blend files.
BODY="$REPO/bodies/mannequin_f/mannequin_f.blend"
if [ -f "$BODY" ] && [ "$(wc -c < "$BODY")" -lt 1024 ]; then
    echo "bodies/*.blend are Git LFS pointers - fetching them (git lfs pull)"
    (cd "$REPO" && git lfs install --local && git lfs pull)
fi

# 2. Python environment.
UV=${BP3D_UV:-$(command -v uv || true)}
if [ -n "$UV" ]; then
    export UV_PYTHON_INSTALL_DIR="$REPO/.python"
    "$UV" python install 3.12
    [ -x "$PY" ] || "$UV" venv --python 3.12 "$VENV"
    "$UV" pip install --python "$PY" -r "$REQ"
else
    if [ ! -x "$PY" ]; then
        BASE=""
        for c in python3.12 python3.13 python3.11 python3.10 python3; do
            if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)'; then
                BASE=$c; break
            fi
        done
        [ -n "$BASE" ] || { echo "Python 3.10-3.13 not found. Install Python 3.12 or uv (https://docs.astral.sh/uv/)." >&2; exit 1; }
        "$BASE" -m venv "$VENV"
    fi
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r "$REQ"
fi
"$PY" -c "import build123d; print('build123d', build123d.__version__)"

# 3. External programs: Blender for the 3D stage, a Chromium-based browser for PNG/PDF of the sheet.
export PYTHONPATH="$REPO"
"$PY" -c "from bp3d.build import find_blender; print('Blender:', find_blender())" \
    || echo "WARNING: Blender 5.3 not found - drawings work, build/render/posetest do not. Set BP3D_BLENDER." >&2
"$PY" -c "from bp3d.__main__ import browser; b = browser(); print('Browser:', b or 'NOT FOUND'); raise SystemExit(0 if b else 1)" \
    || echo "WARNING: Chrome/Chromium/Edge not found - drawings are written as SVG only. Set BP3D_BROWSER." >&2

echo "Blueprint3D ready: $VENV"
echo "Check the tool:  PYTHONPATH=\"$REPO\" \"$PY\" -m bp3d selftest"
