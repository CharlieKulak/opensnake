# OpenSnake in a web browser

This folder builds the browser version of OpenSnake and serves it so anyone on
your local network can play it at an address like `http://192.168.1.248:8000/`.
It uses [pygbag](https://pypi.org/project/pygbag/), which packages the
pygame game to run in the browser with WebAssembly. The game code itself is the
same as the desktop version (`../opensnake/`).

| File | What it does |
| --- | --- |
| `build.sh` | Builds the browser version into `build/` (and can start the server) |
| `serve.py` | Serves the built game on your local network |
| `main.py` | The browser entry point that starts the game |
| `build/` | Build output. Created by `build.sh`, ignored by git, safe to delete |

## First-time setup

Run these from the project folder (the one containing `web-support/`). You only
need to do this once. If you already have the `.venv` folder from the desktop
setup, skip the first line.

```sh
python3 -m venv .venv
.venv/bin/pip install -e . pygbag
```

## Start the server

Build the game and start the server in one step:

```sh
PYTHON=.venv/bin/python web-support/build.sh --serve
```

When it's ready it prints the addresses to open:

```
OpenSnake is being served from .../web-support/build/opensnake/build/web
  On this computer:      http://localhost:8000/
  On your local network: http://192.168.1.248:8000/
Press Ctrl+C to stop.
```

Open the local network address on any phone, tablet or computer connected to
the same Wi-Fi or network. Click the page once to start: browsers don't allow
game sound until you interact with the page.

**To stop the server**, press **Ctrl+C** in the terminal where it's running.

### Start it again later

If you haven't changed the game since the last build, you can skip building and
just start the server:

```sh
.venv/bin/python web-support/serve.py
```

After changing the game's code, run `build.sh --serve` again so the browser gets
the new version.

### Options

| Want to... | Run |
| --- | --- |
| Use a different port (e.g. 9000) | `.venv/bin/python web-support/serve.py --port 9000` |
| Only build, without serving | `PYTHON=.venv/bin/python web-support/build.sh` |
| Serve a build from somewhere else | `.venv/bin/python web-support/serve.py path/to/build/web` |

## Playing in the browser

- **Display** in the menu chooses the canvas resolution: 16:9 sizes from
  1024 x 576 to 3840 x 2160, or **Fullscreen**, which fills your monitor at its
  own resolution. **F11** switches fullscreen on and off. The page scales the
  game to fit the browser window.
- There is no Quit button; close the tab instead.

## Things to know

- **Internet is needed** the first time a browser loads the page: it downloads
  pygbag's Python runtime from `pygame-web.github.io`. The game files
  themselves come from your computer.
- **Settings and best scores may reset** when the page is reloaded.
- **Only your local network can reach it.** Other devices must be on the same
  network as the computer running the server. If they can't connect, check that
  your firewall allows incoming connections on the port (8000 by default).
- **The server stops** when you press Ctrl+C or close the terminal.
- `serve.py` is meant for home use while developing and testing. To put the
  game on a public website, upload the contents of
  `build/opensnake/build/web/` to any static web host, such as GitHub Pages.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No index.html in ...` | Build first: `PYTHON=.venv/bin/python web-support/build.sh` |
| `Address already in use` | Another server is using the port. Stop it, or use `--port 9000` |
| Grey page that never starts | Click the page. If it still doesn't start, add `?-i` to the address (e.g. `http://localhost:8000/?-i`) to show pygbag's console with any error messages |
| `No module named pygbag` | Run the first-time setup above |
