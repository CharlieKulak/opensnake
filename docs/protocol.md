# The OpenSnake protocol

How a client talks to an OpenSnake server. A client is any game that speaks
this; [Crustacean](https://github.com/CharlieKulak/crustacean) (Rust) and
[PySnake](https://github.com/CharlieKulak/pysnake) (Python) are two.

A server's site is its own world: its own accounts, snake points, items,
records and matches. A client either talks to the site it was loaded from (a
web client) or lets the player type a site's address (a desktop client).

- [HTTP API](#http-api)
- [Matches (WebSocket)](#matches-websocket)
- [Speedruns and the rules](#speedruns-and-the-rules)
- [The catalogue](#the-catalogue)
- [Web clients on a site](#web-clients-on-a-site)

## HTTP API

JSON over HTTP(S). Requests that need an account send
`Authorization: Bearer <token>`, with the token from register or login. Errors
come back with a 4xx status and `{"error": "a sentence to show the player"}`;
401 means the token is missing or no longer valid (log in again).

`GET /api/info` returns `{"server": "OpenSnake", "version", "site"}`. Use it to check that an address really is an OpenSnake server.

### Accounts and profiles

| Request | Body | Reply |
| --- | --- | --- |
| `POST /api/register` | `{username, password}` | `{token, username}` (usernames: 3 to 20 letters, numbers, `_` or `-`; passwords: at least 6 characters) |
| `POST /api/login` | `{username, password}` | `{token, username}` |
| `POST /api/logout` | | `{}` |
| `GET /api/me` | | your profile, plus `points`, `inventory` (items you own), `counts` (copies of each) and `best_rank` |
| `POST /api/profile` | `{bio?, avatar?, skin?}` | your profile. `avatar` is `"icon:colour"`; `skin` is a skin id you own, or `""` for none |
| `POST /api/profile/picture` | `{png}` (base64, at most 256 x 256 and 256 KB) | your profile, with `avatar` = `"custom:<version>"` |
| `GET /api/pictures/{name}` | | `{png, version}`: a player's own picture |
| `GET /api/users?q=` | | `{users: [...]}`, searched by name |
| `GET /api/users/{name}` | | a player's profile, plus `friend`: `none`, `friends`, `outgoing` or `incoming` |

### Friends and messages

| Request | Body | Reply |
| --- | --- | --- |
| `GET /api/friends` | | `{friends, incoming, outgoing}`: lists of players (with `online` and `in_match`) |
| `POST /api/friends/add` | `{name}` | send a friend request, or accept theirs |
| `POST /api/friends/remove` | `{name}` | unfriend, decline or cancel |
| `GET /api/messages` | | `{chats: [{name, avatar, last, unread, ...}], unread}` |
| `GET /api/messages/{name}?before=id` | | `{messages: [...]}`, oldest first (and marks theirs read) |
| `POST /api/messages` | `{to, body}` | the message. Only friends can message each other; it's also pushed live as `dm` |

### Snake points, the store and the market

| Request | Body | Reply |
| --- | --- | --- |
| `POST /api/rounds` | `{fruit}` | `{earned, points}`: points for a finished single-player round |
| `POST /api/store/buy` | `{item}` | `{item, points}`: buy a shop item (`"skin:id"` or `"pack:id"`) |
| `POST /api/store/open` | `{crate}` | `{item, new, copies, points}`: open a loot box |
| `GET /api/market?q=&rarity=&sort=cheap\|pricey\|new` | | `{listings, mine, fee, min, max}` |
| `POST /api/market/list` | `{item, price}` | put one copy up for sale |
| `POST /api/market/cancel` | `{id}` | take a listing down (the copy comes back) |
| `POST /api/market/buy` | `{id}` | `{item, name, price, fee, points, copies}`; the seller is told live with `sold` |

### Battle pass and daily challenges

| Request | Body | Reply |
| --- | --- | --- |
| `GET /api/battlepass` | | this week's pass: `week`, `left`, `owned`, `price`, `xp`, `level`, `level_xp`, `into_level`, `tiers` |
| `POST /api/battlepass/buy` | | `{pass, points}` |
| `POST /api/battlepass/claim` | `{level}` | `{tier, ...}` (points, or a loot box opening, or an item) |
| `GET /api/daily` | | `{day, left, challenges: [{id, text, goal, progress, done, claimed, reward}], bonus, bonus_ready, bonus_claimed}` |
| `POST /api/daily/claim` | `{id}` (0 to 2, or `"bonus"`) | the daily info and your new `points` |

### Speedruns and leaderboards

| Request | Body | Reply |
| --- | --- | --- |
| `GET /api/records` | | `{records: {category: {time_ms, player, date}}}` |
| `GET /api/leaderboard/{category}` | | `{entries: [{player, time_ms, date}]}` |
| `POST /api/runs` | a run file (see below) | `{valid, message, time_ms, rank, rank_before, pb, wr, earned, points}` |
| `GET /api/weekly` | | `{week, left, categories: [{id, name, desc, players, wr, def}]}`: this week's 10 |
| `GET /api/categories?q=&sort=top\|popular\|new` | | `{categories: [{id, name, def, creator, players, votes, voted, mine, wr}]}`: community categories |
| `POST /api/categories/vote` | `{id, up}` | `{id, votes, voted}`: upvote one (not your own), or `up: false` to take it back |
| `POST /api/categories/rename` | `{id, name}` | rename a community category you made |
| `GET /api/rankings` | | `{players, me, total, parts}`: everyone's score out of 100 |
| `GET /api/matches?q=` | | `{total, matches}`: public versus matches to join |
| `GET /api/clients` | | `{default, clients: [{name, path}]}`: the web clients this site serves |

## Matches (WebSocket)

Connect to `/ws` (`wss://` on an HTTPS site). The server sends
`{"t": "welcome", "id", "name", "account"}`. To play as your account, send
`{"t": "auth", "token"}` first; it answers with another `welcome`. Players
without an account can connect with `/ws?name=GuestName` to play as a guest.

Every message is a JSON object with a type in `t`.

**From the client:**

| `t` | Fields | What it does |
| --- | --- | --- |
| `hello` | | just connect (shows you online to friends) |
| `ping` | `at` | the server answers `pong` with the same `at`: your round trip |
| `host` | `settings`, `ranked`, `public`, `name`, `bots` | host a match. `settings`: `{size: small\|medium\|large, speed: 0..1, apples, goal, modes}` |
| `join` | `code` | join a match by its 4-letter code |
| `leave` | | leave the match |
| `team` | `team` | switch team (0 or 1) |
| `settings` | `settings` | the host changes the settings |
| `details` | `name`, `public`, `ranked` | the host renames the match, or makes it public or unranked |
| `add_bot` / `remove_bot` | `team`, `level` / `id` | the host adds or removes a bot (`easy`, `normal`, `hard`) |
| `invite` | `name` | invite an online friend |
| `start` / `rematch` | | the host starts, or starts again after a match |
| `input` | `d`, `step` | turn (`up`, `down`, `left`, `right`). `step` is the move it's for (see below) |

**From the server:** `room` (the lobby: players, teams, settings, `host`,
`code`, `ranked`, `public`), `start` (`state`, `you`: your snake's index,
`tick_ms`), `countdown` (`n`, then 0 to go), `state` (`s`: the game, every
move), `over` (`winner`, `scores`), `reward` (`points`, `balance`, `ranked`,
`rp`, `rp_change`, `rank`, `rank_ups`), `error` (`msg`), `pong`, plus pushes
that can come at any time: `invite` (`from`, `code`, `match`), `invited`,
`friends` (refresh the friend list), `dm` (a message) and `sold` (your market
listing sold).

**The game state** (`state` and `start`) has `w`, `h`, `tick`, `over`,
`winner`, `started`, `goal`, `modes`, `dim`, and:

- `snakes`: `[{b: [[x, y, hole], ...], d, dead, team, score, shield, name, ni}]`.
  `b` is the body, head first; `ni` means don't animate this move (a teleport).
- `apples`: `[[x, y, fruit, group, poison, locked]]`.
- `walls`: `[[x, y, kind, dim]]`.
- `items`: `[[x, y, kind, group]]`.
- `events`: what happened this move, `[[type, x, y, fruit, snake]]`.

**Turns and lag.** The server runs the match and moves every snake once a
tick. A turn has to arrive before the move it's for, so a client aims each
turn at a move it can reach in time and says which in `step`. That's the
server's current move plus `floor((time since its last state + ping + 20 ms) /
tick_ms) + 1`. The server holds early turns until their move. A turn up to one
move late is still applied where it was meant, if nothing got in the way. A
client can show its own turn straight away (prediction) for the move it's
aimed at.

## Speedruns and the rules

A run is played locally, then sent to the server, which replays it to check
the time before it counts. So a client must play by exactly these rules:

- `opensnake/game.py`, `modes.py` and `speedrun.py` define them.
- Every random choice comes from Python's `random.Random(seed)`, the Mersenne
  Twister, used in exactly the same order. Crustacean's `src/pyrandom.rs` and
  `src/game.rs` show how to do that in another language.
- `tools/export_catalog.py` writes `golden.json`: random numbers and recorded
  runs a client can test itself against.

A run file:

```json
{"format": 1, "game": "opensnake", "game_version": "your client's version",
 "category": "sprint10", "seed": 12345, "time_ms": 8580, "time": "0:08.580",
 "splits_ms": [800, ...], "inputs": [[0, "up"], [3, "left"], ...],
 "player": "name", "date": "2026-11-15T12:00:00Z"}
```

- `inputs` holds each turn and the tick it was pressed on.
- `time_ms` is the in-game time: the sum of every move's length, rounded half
  to even.
- Custom categories also send `category_def` (their rules). Their id is a hash
  of those rules.

## The catalogue

Skins, packs, loot boxes, ranks, modes and the built-in speedrun categories
are defined in `opensnake/cosmetics.py`, `modes.py` and `speedrun.py`.
`tools/export_catalog.py` exports them as `catalog.json` for clients written in
other languages. Item ids are `"skin:<id>"` and `"pack:<id>"`; skins carry
their colour pattern, so every client can draw them the same way.

## Web clients on a site

A site serves the web builds in `web-support/clients/<name>/` at `/<name>/`,
and its default client at `/` (see [web-support/README.md](../web-support/README.md)).
A web client finds its server at its own page's origin.
