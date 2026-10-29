# OpenSnake website and server

This folder builds the browser version of OpenSnake and runs the **OpenSnake
server**, which serves the game and adds the online features:

- **Accounts**: players create a username and password and stay logged in on
  that browser.
- **Site world records**: logged-in players' speedrun times go on this site's
  own leaderboards. Every run is replayed by the server to check the time
  before it counts.
- **Versus**: 1v1 up to 4v4 matches. One player hosts and gets a 4-letter
  code, others join with it. Browser and desktop players can play together.

Each server keeps its own accounts and records in its own data folder, so two
websites running OpenSnake have completely separate logins and leaderboards.

| File | What it does |
| --- | --- |
| `build.sh` | Builds the browser game into `build/`; with `--serve` it then starts the OpenSnake server |
| `main.py` | The browser entry point that starts the game |
| `serve.py` | A plain file server for the release download (no accounts, records or versus) |
| `opensnake.service` | systemd service to run the server in the background on Linux |
| `build/` | Build output. Ignored by git, safe to delete |
| `data/` | The server's accounts and records (`opensnake.db`). Ignored by git; back it up |

The server itself is `opensnake/server.py` in the game package.

## Running the website

Do this on the computer that hosts the website, from a clone of the
repository.

### First-time setup

```sh
git clone https://github.com/CharlieKulak/opensnake.git
cd opensnake
python3 -m venv .venv
.venv/bin/pip install -e ".[server]" pygbag
```

### Build and start

```sh
PYTHON=.venv/bin/python web-support/build.sh --serve
```

This builds the browser game and starts the server on port 8000:

```
OpenSnake server 0.3.1
  data:     .../web-support/data
  web game: .../web-support/build/opensnake/build/web
  http://localhost:8000/   (Ctrl+C to stop)
```

Anything after `--serve` is passed to the server, for example
`web-support/build.sh --serve --port 9000`.

To start the server again without rebuilding:

```sh
.venv/bin/python -m opensnake.server
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--port` | `8000` | Port to listen on |
| `--host` | `0.0.0.0` | Address to listen on (`127.0.0.1` = only this computer, e.g. behind a proxy) |
| `--web` | `web-support/build/opensnake/build/web` | The built browser game |
| `--data` | `web-support/data` | Where accounts and records are stored |

**To stop it**, press Ctrl+C.

### Run it as a service (Linux, systemd)

`web-support/opensnake.service` keeps the server running in the background,
restarts it if it crashes and starts it when the computer boots. It's set up
for a repository at `/opt/opensnake`; if yours is elsewhere, edit the paths
in the file first. It runs the server as its own `opensnake` user, which can
only write to `web-support/data/`; the code stays owned by root, so set it up
and update it as root.

```sh
cd /opt/opensnake
PYTHON=.venv/bin/python web-support/build.sh        # build the web game (needs internet)
useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin opensnake
cp web-support/opensnake.service /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/opensnake.service   # optional check
systemctl daemon-reload
systemctl enable --now opensnake
```

| To... | Run |
| --- | --- |
| See if it's running | `systemctl status opensnake` |
| Watch its output | `journalctl -u opensnake -f` |
| Restart it (after an update) | `systemctl restart opensnake` |
| Stop it / stop starting at boot | `systemctl stop opensnake` / `systemctl disable opensnake` |

The service listens on port 8000 on every address (edit `--host` in the file
to `127.0.0.1` if your HTTPS proxy runs on the same machine) and can only
write to `web-support/data/`. When it's running this way, don't also start it
with `build.sh --serve`: the port would already be in use. To run it by hand
against the same data, stop the service and start it as the `opensnake` user,
not root, or the database files can end up owned by root and the service won't
be able to write them:

```sh
setpriv --reuid=opensnake --regid=opensnake --init-groups .venv/bin/python -m opensnake.server
```

### Updating

```sh
git pull
.venv/bin/pip install -e ".[server]"
PYTHON=.venv/bin/python web-support/build.sh --serve
```

With the systemd service, rebuild and restart instead:

```sh
git pull
.venv/bin/pip install -e ".[server]"
PYTHON=.venv/bin/python web-support/build.sh
systemctl restart opensnake
```

Accounts and records in `web-support/data/` are kept across updates.

### HTTPS (a real domain)

Browsers on an `https://` page can only talk to an `https://`/`wss://`
server. Run the OpenSnake server on a local port and put your usual HTTPS
proxy in front of it. The proxy must pass **WebSocket** connections through
on `/ws`, or versus won't connect.

**Caddy** (handles WebSockets automatically):

```
snake.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

**nginx**:

```nginx
server {
    server_name snake.example.com;
    # ... your existing ssl_certificate lines ...
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }
}
```

Behind a proxy, start the server with `--host 127.0.0.1` so it's only
reachable through the proxy.

### Accounts and records data

Everything is in one SQLite file, `web-support/data/opensnake.db`:

- accounts (usernames and salted, hashed passwords), login sessions
- every verified speedrun run, used for the leaderboards and world records

Back up that file to keep your players' accounts and records. Delete it (with
the server stopped) to start fresh.

## Playing on the website

- Click the page once to start (browsers need a click before game sound).
- **Online** in the menu (or **O**) shows this site's server, your account,
  and versus. You stay logged in on that browser until you log out.
- While you're in a match, the browser tab's title shows the match code.
- **Display** picks the canvas resolution (16:9 sizes) or **Fullscreen**
  (also **F11**).
- There's no Quit button; close the tab instead.

## The release download

Each release includes `OpenSnake-<version>-web.zip`: the browser game,
already built, plus `serve.py`. That plays fine for single-player, but it's
static files only, so there are no accounts, site records or versus. Unzip it
and run `python3 serve.py` inside the folder. For the online features, run
the full server from the repository as described above.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No module named aiohttp` | Run the first-time setup: `.venv/bin/pip install -e ".[server]"` |
| `No module named pygbag` | `.venv/bin/pip install pygbag` |
| `Address already in use` | Another server uses the port. Stop it, or use `--port 9000` |
| Online screen says the website doesn't run the OpenSnake server | The site is being served by something else (e.g. `serve.py` or a static host). Start `opensnake.server` |
| Versus can't connect, but logging in works | Your HTTPS proxy isn't passing WebSockets on `/ws`. See the nginx example above |
| Grey page that never starts | Click the page. If it still doesn't start, add `?-i` to the address to show pygbag's console |
| The game needs internet the first time | It downloads pygbag's Python runtime from `pygame-web.github.io` |
