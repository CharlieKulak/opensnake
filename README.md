https://snake.charliekulak.com
###                                                 ###
###         FULLY AI GENERATED, Don't @ me.         ###
###                                                 ###

# OpenSnake

OpenSnake is a server for snake games, and the rules they play by. A site
running it keeps accounts, snake points, skins, ranks, world records and versus
matches. Any game that speaks the [OpenSnake protocol](docs/protocol.md) can
play on it, a bit like Matrix, where one kind of server has many clients.

## Clients

| Client | What it is |
| --- | --- |
| [**Crustacean**](https://github.com/CharlieKulak/crustacean) | Rust, for desktop and the browser, with a 3D view. The default client on https://snake.charliekulak.com |
| [**PySnake**](https://github.com/CharlieKulak/pysnake) | Python and pygame: the original OpenSnake game. **Outdated and no longer maintained**, replaced by Crustacean. Still at https://snake.charliekulak.com/py/ |

Players on different clients share the same accounts, leaderboards and matches.
To write your own client, start with [docs/protocol.md](docs/protocol.md).

## What a site has

- **Accounts** with profiles, pictures, bios, friends and messages between friends.
- **Speedruns.** There are 29 built-in categories, 10 new weekly ones every
  week, and community categories that players make, upvote and search. Every
  run is replayed by the server before it counts, so times can't be faked.
- **Versus** from 1v1 up to 4v4, ranked or unranked, with bots, invites and
  public match search. The server runs every match, and clients predict their
  own turns so they feel instant.
- **Snake points**, earned by playing and spent on a store of skins and packs,
  loot boxes, a weekly battle pass and daily challenges. There's also a player
  market for selling spare copies.
- **Ranks** from Hatchling to Basilisk, with a one-off reward for each, and a
  community leaderboard that scores every player out of 100.

## Running a site

```sh
git clone https://github.com/CharlieKulak/opensnake.git
cd opensnake
python3 -m venv .venv
.venv/bin/pip install -e ".[server]"
web-support/install-client.sh crustacean https://github.com/CharlieKulak/crustacean/releases/latest/download/crustacean-web.zip
.venv/bin/opensnake-server
```

Then open http://localhost:8000/. For running it as a service, HTTPS, updating
and more clients, see [web-support/README.md](web-support/README.md).

## Code

| File | Contents |
| --- | --- |
| `opensnake/server.py` | The server: the HTTP API, versus matches, the database, serving web clients. |
| `opensnake/game.py` | The game rules and simulation. Clients play by these, and the server runs matches and replays runs with them. |
| `opensnake/modes.py` | The modes, which mix, speeds and board limits. |
| `opensnake/speedrun.py` | Speedrun categories (built-in, weekly and custom), the timer, run files and verifying them. |
| `opensnake/cosmetics.py` | Snake points, skins and their colour patterns, packs, loot boxes, ranks, the battle pass and daily challenges. |
| `opensnake/bots.py` | Computer players for versus. |
| `opensnake/weeks.py` | Weeks, for the battle pass and weekly speedruns. |
| `opensnake/registry.py` | Hooks a client's mods can add to the rules (PySnake's mods use it). |
| `tools/export_catalog.py` | Exports the catalogue and test data for clients in other languages. |
| `docs/protocol.md` | The protocol, for client authors. |
| `web-support/` | Running a site: the systemd service, updating, installing web clients. |

Python clients can depend on this package for the rules (`pip install
opensnake`, without the `[server]` extra, needs nothing else).

### Tests

```sh
python -m unittest discover tests
```

These cover each mode's rules, speedrun replays and verification, the whole
API (accounts, the store and market, the battle pass, daily challenges,
friends, messages, rankings and community categories), versus matches and lag
handling, and serving web clients.

## License

BSD 3-Clause; see [LICENSE](LICENSE). The clients have their own licenses
(Crustacean and PySnake are GPL).
