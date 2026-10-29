#!/bin/sh
# Build the browser version of OpenSnake with pygbag.
#
#   web-support/build.sh          build into web-support/build/opensnake/build/web/
#   web-support/build.sh --serve  build, then start the OpenSnake server (website,
#                                 accounts, records and versus) on your network
#
# Needs: pip install pygbag   (and for --serve: pip install aiohttp)
set -e
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
src="$here/build/opensnake"  # the folder name becomes the game package name (opensnake.*)
python=${PYTHON:-python3}

rm -rf "$src"
mkdir -p "$src"
cp "$here/main.py" "$src/main.py"
# Copy the game package without caches. The server code stays out: it isn't
# part of the browser game, and its aiohttp import would break the build.
(cd "$root" && tar --exclude='__pycache__' --exclude='opensnake/server.py' -cf - opensnake) | (cd "$src" && tar -xf -)
cp "$root/packaging/linux/opensnake-256.png" "$src/favicon.png"

"$python" -m pygbag --build --title OpenSnake "$src"

# Name the game files after their contents (opensnake-<hash>.tar.gz) and point
# index.html at them. index.html is never cached, so every build is fetched
# under a new name and a browser can't keep playing an old copy.
"$python" - "$src/build/web" <<'PY'
import hashlib, sys
from pathlib import Path
web = Path(sys.argv[1])
page = web / "index.html"
html = page.read_text(encoding="utf-8")
for ext in ("tar.gz", "apk"):
    old = web / f"opensnake.{ext}"
    new = f"opensnake-{hashlib.sha256(old.read_bytes()).hexdigest()[:12]}.{ext}"
    assert html.count(f'"{old.name}"') == 1, f"index.html doesn't load {old.name} the expected way"
    html = html.replace(f'"{old.name}"', f'"{new}"')
    old.rename(web / new)
page.write_text(html, encoding="utf-8")
PY
echo "Built: $src/build/web/"

if [ "$1" = "--serve" ]; then
    shift
    cd "$root"
    exec "$python" -m opensnake.server --web "$src/build/web" "$@"
fi
