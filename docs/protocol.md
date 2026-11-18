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
| `POST /api/rounds` | `{round: {seed, settings, inputs}}` | `{earned, fruit, points}` (and `message` when it pays nothing): points for a finished single-player round. The server replays the round to count the fruit (`settings`: `w`, `h`, `modes`, `fruit_count`, `fruit`, `tick_ms`, `accel`; `inputs` as in a run file). Rounds that ate nothing, a round sent twice, or one sent sooner than it could have been played pay nothing; rounds pay at most 150,000 a day; and only one account per network (IP address) earns from playing at a time |
| `POST /api/store/buy` | `{item}` | `{item, points}`: buy a shop item (`"skin:id"` or `"pack:id"`) |
| `POST /api/store/open` | `{crate}` | `{item, new, copies, points}`: open a loot box |
| `GET /api/market?q=&rarity=&sort=cheap\|pricey\|new` | | `{listings, mine, fee, min, max}` |
| `POST /api/market/list` | `{item, price}` | put one copy up for sale |
| `POST /api/market/cancel` | `{id}` | take a listing down (the copy comes back) |
| `POST /api/market/buy` | `{id}` | `{item, name, price, fee, points, copies}`; the seller is told live with `sold` |
| `GET /api/users/{name}/items` | | `{name, items: {item: copies}}`: what a player could trade |
| `GET /api/trades` | | `{incoming, outgoing, history}`: trade offers (`from`, `to`, `give`, `give_points`, `want`, `want_points`, `status`) |
| `POST /api/trades` | `{to, give, give_points, want, want_points}` | offer a trade (up to 12 items a side; ranked skins can't be traded); the other player is told live with `trade` |
| `POST /api/trades/answer` | `{id, action}` | `accept` or `decline` one offered to you, `cancel` your own; everything moves at once, or nothing does |
| `GET /api/jackpot` | | the pot: `{round, players: [{name, avatar, items, value, chance}], total, seconds_left, countdown, last, history}`. `last` is the latest draw (its `winner` and players), for the winner animation |
| `POST /api/jackpot/enter` | `{items}` | put up to 20 skins or packs in the pot (held until the draw). The draw is 45 s after a second player joins; one player wins everything, their chance being their share of the pot's value (an item's shop price, or else a value by rarity). Players in the draw are told with `jackpot` (`winner`, `total`, `you_won`). A pot nobody else joins in 24 h goes back to its player |

### Battle pass and daily challenges

| Request | Body | Reply |
| --- | --- | --- |
| `GET /api/battlepass` | | this week's pass: `week`, `left`, `owned`, `price`, `xp`, `level`, `level_xp`, `into_level`, `tiers` |
| `POST /api/battlepass/buy` | | `{pass, points}` |
| `POST /api/battlepass/claim` | `{level}` | `{tier, ...}` (points, or a loot box opening, or an item) |
| `GET /api/daily` | | `{day, left, challenges: [{id, text, goal, progress, done, claimed, reward}], bonus, bonus_ready, bonus_claimed}` |
| `POST /api/daily/claim` | `{id}` (0 to 2, or `"bonus"`) | the daily info and your new `points` |
| `GET /api/login-reward` | | `{ready, streak, step, rewards, milestones}`: today's login reward. A 30-day ladder, better each day in a row; `rewards` names each day, `milestones` the big ones (`{day, reward}`, e.g. day 15: 250,000 snake points, day 30: 2 Royal Crates and 500,000) |
| `POST /api/login-reward/claim` | | `{kind, reward, points, opened}`: `opened` lists every loot box the day gave (`{crate, item, new, copies}`); the first one is also at the top level |

### Story mode

Eight chapters of ten levels, each ending in a boss duel (`opensnake/story.py`; the
catalogue's `story` has every level, challenge and boss). A level is played like a speedrun
(category `story-s1-01` and so on, built from the level's rules) and checked by replaying it.

| Request | Body | Reply |
| --- | --- | --- |
| `GET /api/story` | | the chapters, with your `stars`, `best_ms` and `unlocked` on each level, and `beaten`/`unlocked` on each boss (no account: nothing unlocked past the first level) |
| `POST /api/story/run` | a run file | `{valid, stars, earned: [3 booleans], new_stars, points_earned, best_ms, next, next_unlocked, points}`. Each star pays once (more per star in later chapters) |

| `POST /api/story/duel/start` | `{boss}` | `{token, seed, boss}`: play that boss's duel on your own computer, from this seed (`opensnake/duel.py`'s `Duel`; Crustacean's `src/duel.rs` and `src/bots.rs` show it in another language) |
| `POST /api/story/duel/finish` | `{token, inputs}` | `{won, seconds, best_chain, sent, ...}`: the server replays the duel from your turns (`[move, direction]`, as you pressed them) and pays a win (`first`, `rewards`, `opened`), if it took at least as long as it would to play |
| `GET /api/presence` | | `{check}`: after 2.5 hours of play, "Are you still here?" (`{code, choices, seconds}`; games ask now and then while playing, and when pushed `presence`). Showing it starts its 20 seconds |
| `POST /api/presence` | `{answer}` | `{ok}`: the right code clears it. No answer in time takes back the last 6 hours of earnings, and the server sends `kicked` (`message`) and closes the connection |

Levels unlock in order; a boss needs its chapter's ten levels, and the next chapter needs the
boss beaten. Star 1 is finishing; stars 2 and 3 are the level's challenges (`time`: finish in
`a` ms; `turns`: at most `a` turns; `split`: the first `a` fruit in `b` ms; `noshield`: no
shield used up).

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
| `GET /api/replay/{category}` | | `{player, time_ms, date, run}`: a built-in or weekly category's world record run (seed and inputs), to watch |
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

**Battles.** A room whose settings have `"format": "battle"` (up to 4 players, people or
bots; always unranked) is played like a boss duel: everyone gets their own board, combos send
junk to the opponent with the least already coming, and the last snake going wins. The
messages are the duel ones below, with `duel_start` also carrying `mode: "battle"`, `you`
(your board) and `players`; attack events say who they went to; `out` events say who crashed;
`duel_over` has `place`, `of`, `winner`, `points_earned` and `balance`.

**Boss duels (story mode)** are played on the player's own computer (see `/api/story/duel/*`
above). The server can also run one: send `{"t": "duel", "boss": n}` (logged in, the boss
unlocked). You and the boss each get a board. The server sends `duel_start` (`boss`,
`tick_ms`, `state`), `duel_countdown` (`n`, then 0), a `duel_state` every move (`s`:
`{tick, tick_ms, over, winner, sides: [yours, the boss's], events, next_signature, sudden}`)
and `duel_over` (`won`, `seconds`, `best_chain`, `sent`; on a win `first`, `rewards`,
`points_earned` and `opened`: loot boxes and the boss's skin). Each side is a game state plus
`arrows`, `temp` (walls that melt), `chain`, `chain_left`, `incoming` (`[[junk, moves till it
drops]]`), `fog`, `overclock`, `best_chain` and `sent`. Steer your board with `input` as in
versus (`step` is your board's move). Fruit eaten within a few moves of each other is a
combo; when it ends it sends junk (1, 2, 4, 6, 9, 12, 16, then 4 more a fruit), cancelling
junk coming your way first. `leave` gives the duel up.

`start` (and a battle's `duel_start` players) include each player's equipped skin (`skins`,
or `skin`; `""` for none), so a client can draw everyone in theirs.

**From the server:** `room` (the lobby: players, teams, settings, `host`,
`code`, `ranked`, `public`), `start` (`state`, `you`: your snake's index,
`tick_ms`), `countdown` (`n`, then 0 to go), `state` (`s`: the game, every
move), `over` (`winner`, `scores`), `reward` (`points`, `balance`, `ranked`,
`rp`, `rp_change`, `rank`, `rank_ups`), `error` (`msg`), `pong`, plus pushes
that can come at any time: `invite` (`from`, `code`, `match`), `invited`,
`friends` (refresh the friend list), `dm` (a message), `sold` (your market
listing sold), `trade` (a trade offered to you, or the `status` of one of yours)
and `jackpot` (a pot you were in was drawn).

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
- Custom categories also send `category_def` (their rules: `w`, `h`, `modes`,
  `goal`, `fruit_count`, `tick_ms`, `fruit`, and `accel` for Accelerate, the ms
  faster per fruit eaten, down to 45 ms). Their id is a hash of those rules
  (`accel` is only included when it isn't 0). `POST /api/categories {def}` shares
  one in Community without playing it first.

## The catalogue

Skins, packs, loot boxes, ranks, modes and the built-in speedrun categories
are defined in `opensnake/cosmetics.py`, `modes.py` and `speedrun.py`.
`tools/export_catalog.py` exports them as `catalog.json` for clients written in
other languages. A crate with a `series` (the Holiday Crate) gives only that
series' skins, which no other crate gives. Item ids are `"skin:<id>"` and `"pack:<id>"`; skins carry
their colour pattern, so every client can draw them the same way.

## Web clients on a site

A site serves the web builds in `web-support/clients/<name>/` at `/<name>/`,
and its default client at `/` (see [web-support/README.md](../web-support/README.md)).
A web client finds its server at its own page's origin.
