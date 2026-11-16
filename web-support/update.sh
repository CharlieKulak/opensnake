#!/bin/sh
# Update this OpenSnake site: pull the server, install any new dependencies,
# update the web clients in clients.list to their latest releases, restart.
#
#   web-support/update.sh
#
# Run it as the user that owns the repository (root for the systemd setup in
# opensnake.service). A client that can't be downloaded keeps its current build.
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
python=${PYTHON:-.venv/bin/python}

git pull --ff-only
"$python" -m pip install -q -e ".[server]"
grep -v '^\s*#' web-support/clients.list | while read -r name source; do
    [ -n "$name" ] || continue
    web-support/install-client.sh "$name" "$source" || echo "Couldn't update the $name client; keeping the one it has."
done

if systemctl is-enabled --quiet opensnake 2>/dev/null; then
    systemctl restart opensnake
    echo "Updated to $(git log -1 --format='%h %s') and restarted the opensnake service."
else
    echo "Updated to $(git log -1 --format='%h %s'). Restart the server to use it."
fi
