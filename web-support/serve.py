"""Serve the browser build of OpenSnake on your local network.

    python web-support/serve.py [BUILD_DIR] [--port 8000]

Anyone on the same network can open the printed address in a browser.
Stop it with Ctrl+C.
"""

import argparse
import functools
import http.server
import socket
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent / "build" / "opensnake" / "build" / "web"


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".apk": "application/octet-stream",
        ".js": "text/javascript",
    }

    def end_headers(self):
        # Always fetch the latest build while developing.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def lan_ip() -> str:
    """This computer's address on the local network (no traffic is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET address; connect() on UDP only picks a route
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", nargs="?", default=str(DEFAULT_DIR))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    root = Path(args.directory)
    if not (root / "index.html").is_file():
        raise SystemExit(f"No index.html in {root}. Build first: web-support/build.sh")
    handler = functools.partial(Handler, directory=str(root))
    with http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler) as server:
        print(f"OpenSnake is being served from {root}")
        print(f"  On this computer:      http://localhost:{args.port}/")
        print(f"  On your local network: http://{lan_ip()}:{args.port}/")
        print("Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
