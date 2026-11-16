#!/bin/sh
# Install (or update) a web client for this OpenSnake site.
#
#   web-support/install-client.sh NAME SOURCE
#
# NAME    the folder in web-support/clients/, and so where it's served: /NAME/
#         (the default client is also served at /; see the server's --default-client)
# SOURCE  a folder with the client's web build (an index.html and its files), a
#         .zip of one, or the https:// address of a .zip (like a release download)
#
# The new build replaces the old one in one step, so players never load half of it.
set -e
here=$(cd "$(dirname "$0")" && pwd)
name=$1
source=$2
if [ -z "$name" ] || [ -z "$source" ]; then
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi
case "$name" in
    api|ws|*/*|.*) echo "Can't call a client '$name'." >&2; exit 2 ;;
esac
clients="$here/clients"
mkdir -p "$clients"
tmp=$(mktemp -d "$clients/.install-XXXXXX")
trap 'rm -rf "$tmp"' EXIT

case "$source" in
    http://*|https://*)
        echo "Downloading $source..."
        if command -v curl >/dev/null; then curl -fsSL -o "$tmp/client.zip" "$source"
        else python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$source" "$tmp/client.zip"; fi
        zip="$tmp/client.zip" ;;
    *.zip) zip=$source ;;
    *) zip="" ;;
esac
if [ -n "$zip" ]; then
    python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$zip" "$tmp/unpacked"
    build="$tmp/unpacked"
else
    build=$source
fi
# The build may sit inside one folder of the zip (like PySnake-3.0.0-web/).
if [ ! -f "$build/index.html" ]; then
    inner=$(find "$build" -mindepth 2 -maxdepth 2 -name index.html | head -1)
    [ -n "$inner" ] || { echo "No index.html in $source: is it a web client build?" >&2; exit 1; }
    build=$(dirname "$inner")
fi
mkdir "$tmp/new"
cp -R "$build"/. "$tmp/new/"
chmod -R a+rX "$tmp/new"
rm -rf "$clients/$name.old"
[ -d "$clients/$name" ] && mv "$clients/$name" "$clients/$name.old"
mv "$tmp/new" "$clients/$name"
rm -rf "$clients/$name.old"
echo "Installed the $name client ($(du -sh "$clients/$name" | cut -f1)). Restart the server if it's new."
