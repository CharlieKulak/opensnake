# Running an OpenSnake site

This folder has what you need to run the OpenSnake server as a website: the
systemd service, the update script, and the web clients the site serves.

| File | What it does |
| --- | --- |
| `opensnake.service` | systemd service to run the server in the background on Linux |
| `update.sh` | Updates a site: pull, install, update the web clients, restart the service |
| `install-client.sh` | Installs or updates one web client, from a folder, a `.zip`, or a download link |
| `clients.list` | The web clients `update.sh` keeps up to date |
| `clients/` | The installed web clients, one folder each. Ignored by git |
| `data/` | The site's accounts and records (`opensnake.db`). Ignored by git; back it up |

## First-time setup

Do this on the computer that hosts the website:

```sh
git clone https://github.com/CharlieKulak/opensnake.git
cd opensnake
python3 -m venv .venv
.venv/bin/pip install -e ".[server]"
```

## Web clients

The server serves the web build of any OpenSnake client. Each one lives in
`clients/<name>/` and is served at `/<name>/`. One client is also the
**default**, served at `/`: Crustacean if it's installed, or whichever one you
choose with `--default-client`.

```sh
# from their latest releases (this is what clients.list does):
web-support/install-client.sh crustacean https://github.com/CharlieKulak/crustacean/releases/latest/download/crustacean-web.zip
# or from a build you made, or a zip of one:
web-support/install-client.sh mine ~/my-client/dist
```

Restart the server after adding a client. Updating one that's already there
takes effect straight away, and players get it the next time they load the
page. `GET /api/clients` lists what a site serves.

A server with no clients still works: it's the API only, for desktop clients.

## Start it

```sh
.venv/bin/opensnake-server
```

```
OpenSnake server 3.0.0
  data:     .../web-support/data
  client:   crustacean at /
  client:   py at /py/
  http://localhost:8000/   (Ctrl+C to stop)
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--port` | `8000` | Port to listen on |
| `--host` | `0.0.0.0` | Address to listen on (`127.0.0.1` = only this computer, e.g. behind a proxy) |
| `--data` | `web-support/data` | Where accounts and records are stored |
| `--clients` | `web-support/clients` | The web clients, one folder each |
| `--default-client` | `crustacean`, if installed | The client served at `/` |
| `--restart-week` | | Start this week over (new weekly speedruns, a fresh battle pass), then exit |

To stop it, press Ctrl+C.

## Run it as a service (Linux, systemd)

`opensnake.service` keeps the server running in the background, restarts it
if it crashes and starts it when the computer boots. It's set up for a
repository at `/opt/opensnake`; if yours is elsewhere, edit the paths in the
file first. It runs the server as its own `opensnake` user, which can only
write to `web-support/data/`. The code stays owned by root, so set it up and
update it as root.

```sh
cd /opt/opensnake
useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin opensnake
cp web-support/opensnake.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now opensnake
```

| To... | Run |
| --- | --- |
| See if it's running | `systemctl status opensnake` |
| Watch its output | `journalctl -u opensnake -f` |
| Restart it | `systemctl restart opensnake` |
| Stop it / stop starting at boot | `systemctl stop opensnake` / `systemctl disable opensnake` |

To run it by hand against the same data, stop the service and start it as the
`opensnake` user, not root. Otherwise the database files can end up owned by
root and the service won't be able to write them:

```sh
setpriv --reuid=opensnake --regid=opensnake --init-groups .venv/bin/opensnake-server
```

## Updating

```sh
web-support/update.sh
```

This pulls the server, installs any new dependencies, updates every client in
`clients.list` to its latest release, and restarts the service. A client that
can't be downloaded keeps the build it has. Accounts and records in `data/`
are kept, and new tables and columns are added to the database automatically.

## HTTPS (a real domain)

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

## The data

Everything is in one SQLite file, `web-support/data/opensnake.db`. It holds:

- accounts (usernames and salted, hashed passwords) and login sessions;
- every verified speedrun;
- profiles and pictures;
- snake points, with a ledger of every change;
- owned items, market listings, the battle pass and daily challenges;
- friends and messages;
- ranks, and community categories with their upvotes.

Back up that file to keep your players' accounts and records. Delete it (with
the server stopped) to start fresh.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No module named aiohttp` | Run the first-time setup: `.venv/bin/pip install -e ".[server]"` |
| `Address already in use` | Another server uses the port. Stop it, or use `--port 9000` |
| The site shows a 404 at `/` | No web client is installed. See "Web clients" above |
| Versus can't connect, but logging in works | Your HTTPS proxy isn't passing WebSockets on `/ws`. See the nginx example above |
