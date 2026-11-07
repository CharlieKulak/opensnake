#!/bin/sh
# Rebuild the browser game if the game has changed since the last build (or
# there isn't one yet), and do nothing otherwise.
#
# The systemd service runs this before starting the server, so after a
# `git pull`, `systemctl restart opensnake` is enough to update the website.
# Needs internet when it does rebuild.
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
python=${PYTHON:-.venv/bin/python}

if "$python" -c '
import sys
from opensnake.server import DEFAULT_WEB, stale_build
built = any(DEFAULT_WEB.glob("opensnake*.tar.gz"))
sys.exit(0 if stale_build(DEFAULT_WEB) or not built else 1)'; then
    echo "The game has changed: rebuilding the web game..."
    PYTHON="$python" web-support/build.sh
else
    echo "The web game is up to date."
fi
