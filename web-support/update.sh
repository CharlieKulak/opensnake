#!/bin/sh
# Update a server to the latest OpenSnake: pull the code, install any new
# dependencies, rebuild the browser game and restart the service.
#
#   web-support/update.sh
#
# Run it as the user that owns the repository (root for the systemd setup in
# opensnake.service). Needs internet for git, pip and the pygbag build.
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
python=${PYTHON:-.venv/bin/python}

git pull --ff-only
"$python" -m pip install -q -e ".[server]" pygbag
PYTHON="$python" web-support/build.sh

if systemctl is-enabled --quiet opensnake 2>/dev/null; then
    systemctl restart opensnake
    echo "Updated to $(git log -1 --format='%h %s') and restarted the opensnake service."
else
    echo "Updated to $(git log -1 --format='%h %s'). Restart the server to use it."
fi
