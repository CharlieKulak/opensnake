#!/bin/sh
# Build the browser version of OpenSnake with pygbag.
#
#   web-support/build.sh          build into web-support/build/opensnake/build/web/
#   web-support/build.sh --serve  build, then serve it on your local network
#
# Needs: pip install pygbag
set -e
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
src="$here/build/opensnake"  # the folder name becomes the game package name (opensnake.apk)
python=${PYTHON:-python3}

rm -rf "$src"
mkdir -p "$src"
cp "$here/main.py" "$src/main.py"
# Copy the game package without caches.
(cd "$root" && tar --exclude='__pycache__' -cf - opensnake) | (cd "$src" && tar -xf -)
cp "$root/packaging/linux/opensnake-256.png" "$src/favicon.png"

"$python" -m pygbag --build --title OpenSnake "$src"
echo "Built: $src/build/web/"

if [ "$1" = "--serve" ]; then
    exec "$python" "$here/serve.py" "$src/build/web"
fi
