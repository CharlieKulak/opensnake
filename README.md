
###                                                 ###
###         FULLY AI GENERATED, Don't @ me.         ###
###                                                 ###

A free, open-source desktop snake game with 19 game modes you can mix
together, boards from 8 x 5 up to 1000 x 1000, asset packs and Python mods.
It runs on Linux, Windows and macOS.

OpenSnake is inspired by the browser snake game found in Google search, but it
is an independent, from-scratch implementation. It contains no code, images or
sounds from Google Snake, and it is not affiliated with or endorsed by Google.
The fruit and item artwork is from [Twemoji](https://github.com/jdecked/twemoji)
(CC-BY 4.0), the eating sounds are CC0 recordings, and everything else is drawn
or synthesized in code. See [CREDITS.md](CREDITS.md).

- [Download](#download)
- [Install and play](#install-and-play)
- [Controls](#controls)
- [The menu](#the-menu)
- [Speedrun](#speedrun)
- [Online play](#online-play)
- [Modes](#modes)
- [How movement works](#how-movement-works)
- [Sounds](#sounds)
- [Settings and scores](#settings-and-scores)
- [Asset packs](#asset-packs)
- [Mods](#mods)
- [For developers](#for-developers)
- [License](#license)

## Download

Ready-to-play builds are on the
[Releases page](https://github.com/CharlieKulak/opensnake/releases). They
include everything, so you don't need Python.

| System | File | How to run |
| --- | --- | --- |
| Windows | `OpenSnake-<version>-windows-x86_64.zip` | Unzip and double-click `OpenSnake.exe`. If Windows SmartScreen warns about an unknown app, click **More info**, then **Run anyway**. |
| macOS (Apple silicon) | `OpenSnake-<version>-macos-arm64.zip` | Unzip and move `OpenSnake.app` to Applications. The first time, right-click it and choose **Open**, then **Open** again (the app isn't signed with an Apple developer certificate). |
| Linux (x86-64) | `OpenSnake-<version>-linux-x86_64.tar.gz` | Extract and run `./OpenSnake`, or install it with a menu entry and icon: `sudo ./install.sh` (see below). |

On Linux, `sudo ./install.sh` (from the extracted folder) installs the game as
`/usr/bin/opensnake` and adds OpenSnake to your applications menu with its
icon. `sudo ./install.sh --uninstall` removes it again. To install just for
yourself without `sudo`, run `PREFIX=~/.local ./install.sh`.

If you installed OpenSnake another way and only want the menu entry, copy
`packaging/linux/opensnake.desktop` to `~/.local/share/applications/` (or
`/usr/share/applications/`) and `packaging/linux/opensnake.svg` to
`~/.local/share/icons/hicolor/scalable/apps/`. The entry runs
`/usr/bin/opensnake`; edit its `Exec=` line if yours is elsewhere.

To play in a web browser, download `OpenSnake-<version>-web.zip`, unzip it,
and run `python3 serve.py` inside the folder; see
[web-support/README.md](web-support/README.md).

The releases also include `opensnake-<version>-py3-none-any.whl` for people
who already have Python: `pip install` it, then run `opensnake`.

## Install and play

To run from source you need Python 3.10 or newer.

```sh
python -m venv .venv
.venv/bin/pip install .          # Windows: .venv\Scripts\pip install .
.venv/bin/opensnake              # Windows: .venv\Scripts\opensnake
```

Or run it straight from the source folder:

```sh
pip install pygame-ce
python -m opensnake
```

Command-line options:

| Option | What it does |
| --- | --- |
| `--assets DIR` | Load an [asset pack](#asset-packs) from `DIR` |
| `--mods DIR` | Also load [mods](#mods) from `DIR` |

## Controls

| Key | In the game | In the menu |
| --- | --- | --- |
| Arrow keys / WASD | Steer | Move between items |
| Left / Right | | Change an option, move the speed slider, change a number |
| Shift + Left / Right | | Change a number by 10 |
| 0-9, Backspace | | Type a fruit count, board width or height |
| Enter / Space | Play again after a game | Select / start typing a number / confirm |
| Esc | Pause, then back to the menu | Back to a paused game; cancel typing |
| P | Pause / resume | |
| R | Restart instantly (great for speedruns) | |
| Insert | | On the Speedrun screen: add your current settings as a category |
| Delete | | On the Speedrun screen: remove a custom category (press twice) |
| B | | Random "Blender" mix of modes |
| T | | Open the Speedrun screen |
| O | | Open the Online screen (accounts, site records, versus) |
| H | | On the Online screen: host a versus match |
| Q | Leave a versus match | |
| M | Mute / unmute | Open Packs & Mods |
| F11 | Fullscreen on/off | Fullscreen on/off |

The mouse works everywhere in the menu: click tiles and buttons, click the
`<` `>` arrows, click a number box to type in it, and drag the speed slider.

## The menu

**Mode tiles.** Click a mode to turn it on or off. Any number can be on at
once. **Classic** turns them all off. A few pairs that make no sense together
switch each other off (Sokoban + Portal, Sokoban + Poison, Portal + Poison).
**Blender** picks a random mix of 2 to 4 modes.

**Fruit.** Apple, orange, cherry, grape, strawberry, lemon, banana, or
**Mixed** (a random fruit each time). Mods can add more.

**Count.** How many fruits are on the board at once, from 1 to 500. Click the
box and type a number, or use the `<` `>` arrows / Left and Right keys (hold
Shift to change by 10). If the board runs out of room, it holds as many as
fit. In Poison mode there are this many good fruits plus this many poison
ones; in Portal mode, this many pairs.

**Snake.** Snake colour.

**Display.** How the window is shown:

- **Window**: a normal window you can resize freely. The game scales to fit.
- **Fixed sizes** from 800 x 600 up to 3840 x 2160, including widescreen and
  ultrawide. Only sizes that fit your monitor are offered.
- **Fullscreen** at your monitor's resolution. F11 switches between fullscreen
  and your last windowed setting.

**Width and Height.** The board size in cells. The default is 10 x 9; any
rectangle from 8 x 5 up to 1000 x 1000 works. Click the box and type a number, then press Enter (numbers
outside the range are clamped), or use the `<` `>` arrows / Left and Right
keys (hold Shift to change by 10).

Boards that fit the window are scaled to fill it. Bigger boards keep the cells
readable and **scroll**: the camera follows the snake, and markers at the
screen edge point to the nearest off-screen fruit with its distance in cells.

**Speed.** A slider with five marked stops:

| Stop | Time per cell | Cells per second |
| --- | --- | --- |
| Slowest | 260 ms | 3.8 |
| Slow | 170 ms | 5.9 |
| Default | 130 ms | 7.7 |
| Fast | 85 ms | 11.8 |
| Fastest | 45 ms | 22.2 |

Any position in between works too; the slider snaps to a stop when you get
close to it. The current speed in cells per second is shown on the right.

A best score is kept separately for every combination of modes, board size,
speed and fruit count.

## Speedrun

Press **Speedrun** in the menu (or **T**) and pick a category. Each category
fixes the board, speed, modes and goal, so everyone's times are comparable.

| Category | Goal | Board | Notes |
| --- | --- | --- | --- |
| Sprint 10 | Eat 10 | 10 x 9 | |
| Sprint 25 | Eat 25 | 10 x 9 | |
| Apple Rush | Eat 30 | 17 x 15 | 5 apples on the board at once |
| Accelerate | Eat 30 | 10 x 9 | Starts at 170 ms per cell and gets 4 ms faster with every apple |
| Full Board | Fill every cell | 8 x 5 | 110 ms per cell |
| Portal Dash | Eat 15 | 12 x 11 | Portal mode |
| Wall Gauntlet | Eat 20 | 10 x 9 | Wall mode |
| Key Hunt | Eat 10 | 12 x 11 | Key mode |
| Twin Turns | Eat 15 | 10 x 9 | Twin mode |
| Minefield | Eat 15 | 12 x 11 | Minesweeper mode |

Unless noted, categories run at the Default speed (130 ms per cell).

**The timer** starts with your first move and stops the moment you reach the
goal. It measures *in-game time*: each move adds exactly one move's worth of
time, so a slow computer or dropped frames never change a result, and pausing
costs nothing. Press **R** at any time to restart instantly.

**PB (personal best)** is your fastest finish in each category, saved on your
computer. During a run, the header shows your time, your progress, and after
each apple a **split** against your PB at the same point: green (`-0.412`)
means you're ahead, red (`+0.260`) behind.

**WR (world record)** is the fastest verified time anyone has submitted. World
records are kept in [`opensnake/records.json`](opensnake/records.json) in this
repository. The game ships with a copy and, when online, downloads the latest
one from GitHub at start-up, so a new record shows up for everyone without an
update. (The browser version uses the copy it was built with.) To turn the
download off, set `"online_records": false` in `settings.json`.

### Custom categories

You can also speedrun **your own settings**. In the main menu, tick
**Speedrun** and set a **Goal** (fruit to eat; 0 means fill the whole board).
Pressing Play then times a run of exactly what the menu is set to: modes,
board size, speed, fruit count and fruit. It works like any other category,
with a timer, splits, a PB and a run file.

To keep a setup, open the Speedrun screen and press **+ Add my settings** (or
Insert). It's saved as a named category, listed under the built-in ones with
its PB and WR. Select a custom category and press Delete twice to remove it;
its PB is kept in case you add it again. Saved categories are stored in
`custom-categories.json` next to `settings.json`, which you can copy to share
your categories with friends.

A custom category's id (like `custom-a1eeb2ba60`) is calculated from its rules,
so everyone who plays the same settings shares the same PB/WR table, whatever
they named it. Run files for custom categories include the full rules, and
`--verify` checks the rules really match the id, so a run can't be passed off
under easier settings. World records for custom categories go in
`records.json` under that id, just like built-in ones.

### Submitting a world record

Every finished run is saved as a small replay file: the random seed and your
key presses, which is enough to replay the run exactly. The files are in a
`speedruns` folder next to `settings.json`, named like
`sprint10-20261026-013533-8580ms.json`.

1. Optionally put your name in `settings.json` as `"player_name": "YourName"`
   before your run, so it's in the file.
2. Open an issue on the
   [GitHub repository](https://github.com/CharlieKulak/opensnake/issues) and
   attach the run file.

Anyone can check a run file, and it can't be faked by editing the time:

```sh
opensnake --verify sprint10-20261026-013533-8580ms.json
# VALID   Sprint 10: valid, 0:08.580 (YourName)
```

The game replays the run and confirms it really finishes in the claimed time.
Maintainers then add it to `opensnake/records.json`:

```json
{
  "format": 1,
  "updated": "2026-10-26",
  "records": {
    "sprint10": {"time_ms": 8580, "player": "YourName", "date": "2026-10-26"}
  }
}
```

Bump `updated` whenever records change: the game keeps whichever copy is
newest.

## Online play

Press **Online** in the menu (or **O**) to connect to an OpenSnake website's
server. In the browser version that's automatically the site you're on. On
the desktop, type the website's address (e.g. `https://snake.example.com`)
and press Connect.

**Accounts.** Create an account with a username and password, or log in. You
stay logged in until you log out: in the browser, logins are remembered for
that site; on the desktop, per server. Each website has its own accounts, so
an account on one OpenSnake site doesn't exist on another.

**Site world records.** While you're logged in, every speedrun you finish is
sent to the site automatically. The server replays it to check the time
(just like `--verify`), then puts it on that site's leaderboard. The finish
screen tells you your rank, or that you set a new world record. The Speedrun
screen's WR column then shows the site's records instead of the global
`records.json`. Each website has its own leaderboards.

**Versus (1v1 up to 4v4).** Press **Host a match** to create a match and get
a 4-letter code; friends enter it under **join with a code**. Browser and
desktop players can play in the same match. In the lobby:

- The host can give the match a **name** and switch it from **Private** to
  **Public**. Private matches can only be joined with the code.
- Players are on the **Blue** or **Orange** team (up to 4 each); use
  **Switch team** to change.
- The host chooses the board size, speed, how much fruit, how to win (last
  snake alive, or first team to 10/20/30 fruit) and which modes are on (Wall,
  Borderless, Cheese, Poison, Portal, Shield, Magnet, Twin, Statue, Key,
  Light).
- The host presses **Start match**. After a 3-2-1 countdown everyone steers
  their own snake.

**Public matches** (or **B** on the Online screen) lists every public match on
that server that's still in its lobby and has room, busiest first. Type to
search by match name, host or code; the list refreshes on its own. Press
**Join** on a match (or **Enter** for the top one).

Crashing knocks only your snake out; you can keep watching. Two snakes moving
into the same cell are both knocked out. You don't need an account to play
versus: guests play under the name typed in the Username box, or a random
guest name. The server runs the match itself, so every player sees the same
game.

To run your own OpenSnake website with accounts, records and versus, see
[web-support/README.md](web-support/README.md).

## Graphics

Fruit, keys, locks, shields, mines (bombs), statues (rocks) and the trophy use
[Twemoji](https://github.com/jdecked/twemoji) artwork, bundled as SVG vector
files and rendered at exactly the size each cell needs. They stay sharp at any
window size, from 800 x 600 to 4K. Poison fruit is the apple tinted purple with
a skull badge. The board, snake, walls, gates, arrows, targets and menu icons
are drawn in code with anti-aliasing.

Twemoji graphics are by Twitter, Inc and other contributors, licensed under
[CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/). Any of them can be
replaced with an [asset pack](#asset-packs). The menu shows the best for the current setup.

## Modes

| Mode | What it does |
| --- | --- |
| Classic | Eat fruit, grow longer, avoid the walls and yourself. |
| Wall | Every fruit you eat drops a new wall on the board. |
| Portal | Fruit comes in pairs. Eat one and you come out of the other. |
| Cheese | Your body has holes you can slither through. |
| Borderless | Leave one side of the board and come back on the other. |
| Twin | Each fruit flips you around: your tail becomes your head. |
| Yin Yang | Steer two point-mirrored snakes at once. They must not touch. |
| Key | Fruit is locked until you collect its matching key. |
| Sokoban | Push fruit onto the targets instead of eating it. |
| Poison | Half the fruit is poison, and which half swaps each time you eat. |
| Dimension | Walls live in two dimensions; eating flips which one is solid. |
| Minesweeper | Hidden mines. Cells you have visited show how many mines touch them. |
| Statue | Eating turns your body to stone, leaving you short again. |
| Light | The board is dark except around your head. |
| Shield | Pick up shields that let you survive one crash. |
| Arrow | Arrow tiles force you to turn the way they point. |
| Magnet | Fruit near your head gets pulled toward you. |
| Gate | Gates open and close on a timer. |
| Peaceful | No game over. Crashing just stops you until you turn. |

## How movement works

The snake moves one cell per tick, but is drawn moving continuously: the head
glides between cells and the body follows a smooth path, bending through each
corner as a quarter circle. The eyes turn with the head.

To curve smoothly, the next turn is locked in when the head is halfway into a
cell. A key pressed before that point turns at the next cell; a key pressed
after it turns one cell later. Up to three turns can be queued, so quick
double-taps (for example a U-turn) work.

Turning stays quick at every speed. The snake can only turn at a cell
boundary, so at slow speeds a turn could wait for most of a slow cell. Instead,
while a turn is waiting, the snake glides through the rest of its current cell
at the Fast speed, turns, then carries on at the speed you picked. The longest
wait before a turn is about a tenth of a second at any speed. Speedrun times
aren't affected: the timer counts each move at the category's speed. (In
versus, the server moves everyone together, so this doesn't apply there.)

## Sounds

Eating plays one of five real crunch recordings, picked at random each time so
it doesn't sound repetitive, at 35% volume. They are from
["7 Eating Crunches"](https://opengameart.org/content/7-eating-crunches) by
StarNinjas, released as CC0 (public domain). All other sounds are synthesized
in `opensnake/audio.py`.

To change how loud a sound is, edit `VOLUMES` in `opensnake/audio.py`, or
replace the sound with an asset pack.

Any sound can be replaced by an [asset pack](#asset-packs) or a [mod](#mods).

## Settings and scores

Settings, best scores and speedrun PBs are saved automatically to:

- Linux: `~/.config/opensnake/settings.json`
- macOS: `~/Library/Application Support/OpenSnake/settings.json`
- Windows: `%APPDATA%\OpenSnake\settings.json`

To keep everything in another folder instead (for example a portable copy on
a USB stick), set the `OPENSNAKE_CONFIG_DIR` environment variable to that
folder. Delete the file to reset everything. Settings files from older versions are
converted automatically, including speeds from the old 3-stop slider. The same
folder holds `speedruns/` (your run files), `custom-categories.json` (your
saved speedrun categories) and `records-cache.json` (the last world records
downloaded).

## Asset packs

Asset packs (resource packs) work like Minecraft's. A pack is a folder of
images, sounds and colours that replace the built-in ones. Anything a pack
doesn't provide uses the built-in version, so a pack can be as small as one
file.

### Turning packs on and off

Press **Packs & Mods** in the menu (or **M**). The left column lists every
pack the game found, each with an on/off switch. You can enable several at
once: enabled packs are listed at the top in priority order, and where two
packs replace the same thing, the higher one wins. Move a pack up or down with
its `^` `v` buttons or Shift+Up/Down. Changes apply instantly.

**Open packs folder** opens the folder where your own packs go:

- Linux: `~/.config/opensnake/resourcepacks/`
- macOS: `~/Library/Application Support/OpenSnake/resourcepacks/`
- Windows: `%APPDATA%\OpenSnake\resourcepacks\`

Put each pack in its own folder there, e.g. `resourcepacks/my-pack/`, then
reopen the Packs & Mods screen.

### Built-in packs

OpenSnake ships with three packs, all off by default:

| Pack | Style |
| --- | --- |
| **Shadow Venom** | Edgy and cartoonish: a midnight board, a horned blood-red snake with glowing slit eyes and fangs, cursed fruit, tombstones, spiked bombs, a skeleton key and darker sound effects. |
| **Grave Viper** | Realistic and grim: shaded art with highlights and depth. A dark olive viper with amber slit eyes on charred stone, glossy blood-red apples, a rotting poison apple, stone bricks, a weathered headstone, a rusted naval mine, antique iron keys and padlocks, a battered steel shield and a snake hiss. |
| **Everforest** | Calm and soft, in the [Everforest](https://github.com/sainnhe/everforest) colour scheme: a muted grey-green board, a sage-to-aqua snake, warm fruit colours, mossy stones and gentle wooden sounds. |

They're in `opensnake/packs/` and are good examples to copy when making your
own.

### Making a pack

A pack folder can contain any of the files below, plus an optional
`pack.json` and a `pack.svg` (or `pack.png`) icon shown in the list:

```json
{
  "name": "My Pack",
  "description": "One line shown under the name.",
  "board_light": "#1c1a22",
  "snake_head": "#c4122f"
}
```

Only use files you have the right to use. The `--assets DIR` option and the
`OPENSNAKE_ASSETS` environment variable still work and always sit on top of
the enabled packs. An old `assets` folder next to `settings.json` shows up in
the list as a pack called "assets".

**Images** (`.svg` recommended, since vectors stay sharp at every size;
`.png`, `.webp`, `.gif`, `.bmp`, `.jpg` also work). Each fills one board cell,
so square images work best.

| File | Used for |
| --- | --- |
| `fruit_apple`, `fruit_orange`, `fruit_cherry`, `fruit_grape`, `fruit_strawberry`, `fruit_lemon`, `fruit_banana` | Fruit (mod fruits work too: `fruit_<name>`) |
| `fruit_poison` | Poison fruit |
| `snake_head` | Snake head, drawn facing **right** (rotated automatically). Replaces the eyes. |
| `snake_head_dead` | Head after a crash (optional) |
| `wall`, `statue`, `gate_open`, `gate_closed` | Board obstacles |
| `key`, `lock`, `shield`, `target`, `mine`, `ring` | Items and markers (`ring` is the portal ring) |
| `trophy`, `skull` | Score bar trophy; skull badge used to build the poison fruit |
| `arrow` | Arrow tile, pointing **right** (rotated automatically) |

**Sounds** (`.ogg`, `.wav`, `.mp3` or `.flac`): `eat`, `turn`, `start`, `die`,
`portal`, `push`, `unlock`, `shieldup`, `shield`, `poison`, `dimension`,
`arrow`, `bump`, `poof`, `win`, plus any sound a mod registers.

**Colours** go in an optional `pack.json`:

```json
{
  "board_light": "#aad751",
  "board_dark": "#a2d149",
  "board_sand": "#e5c29f",
  "board_sand_dark": "#d7b899",
  "border": "#578a34",
  "header": "#4a752c",
  "snake_head": "#3d6fe8",
  "snake_tail": "#7aa2ff"
}
```

## Mods

Mods add new game modes, fruits and sounds, written in Python. The right
column of the **Packs & Mods** screen lists every mod found, with its status
(loaded, failed, off) and an on/off switch. Mods set themselves up when the
game starts, so turning one on or off takes effect after a restart: the screen
shows a **Restart now** button when there's a change waiting. **Open mods
folder** opens the mods folder. A mod mode
shows up in the menu next to the built-in ones and can be mixed with them in
Blender.

> **Mods are ordinary Python code and can do anything a program on your
> computer can do. Only install mods from people you trust.**

Mods are for offline play. While any mod is on, the game won't host or join
versus matches or submit speedruns to a site, and the Online screen says so.
Turn mods off in Packs & Mods and restart to play online. Resource packs are
fine online: they only change how the game looks and sounds. Servers also
reject any run whose custom category uses a mode that isn't built in.

### Installing a mod

Put the mod in a mods folder and start OpenSnake. It looks in:

1. the folder given with `opensnake --mods DIR`
2. the `OPENSNAKE_MODS` environment variable
3. a `mods` folder next to `settings.json`, for example
   `~/.config/opensnake/mods/` on Linux

A mod is either a single file (`my_mod.py`) or a folder containing an
`__init__.py` (use a folder when the mod ships images or sounds). Files and
folders whose names start with `_` or `.` are ignored.

The bottom of the menu says how many mods loaded. If a mod fails, the menu
says so and the error is printed in the terminal; the game carries on without
it. If a mod's hook crashes during play, that hook is switched off and the
error is printed, so a buggy mod can't crash the game.

To try the included example:

```sh
opensnake --mods examples/mods
```

### Writing a mod

Every mod defines a `setup(api)` function. OpenSnake calls it once at start-up
with a `ModAPI` object, which the mod uses to register what it adds.

```python
def setup(api):
    def on_step(game):
        if game.tick % 50 == 0:
            game.spawn_wall()          # a new wall every 50 moves

    api.add_mode("rubble", "Rubble", "Walls keep appearing, eat or no eat.",
                 on_step=on_step)
```

[`examples/mods/hunger.py`](examples/mods/hunger.py) is a complete example: a
"Hunger" mode (your tail shrinks if you don't eat in time, with a hunger bar
drawn on the board and its own menu icon) and a kiwi fruit.

### `api.add_mode(mode_id, name, description, **hooks)`

- `mode_id`: unique id, lowercase letters, digits and `_` (max 32 characters).
  Used in settings and score keys, so don't change it once people use it.
- `name`: shown on the menu tile.
- `description`: shown when the tile is selected.
- `conflicts=("other_id", ...)`: modes that get switched off when this one is
  switched on (and the other way round).

Hooks (all optional; each receives the `Game`):

| Hook | Called | Return |
| --- | --- | --- |
| `on_reset(game)` | When a new game is set up | |
| `on_step(game)` | Every tick, after all snakes have moved | |
| `on_move(game, snake)` | Each time a snake moves into a new cell, before it eats | |
| `on_score(game, snake)` | When a fruit is scored, before new fruit spawns | |
| `blocks(game, x, y)` | When a head tries to enter cell `(x, y)` | A reason string (e.g. `"lava"`) to make it solid, or `None` |
| `draw(surface, game, view)` | Every frame, after the snakes are drawn | |
| `icon(surface, size)` | Once, to draw the menu icon on a `size` x `size` surface | |

Without an `icon` hook, the tile shows the mode's first letter.

Hooks only run while their mode is switched on.

### `api.add_fruit(name, label, draw, color=(220, 60, 60))`

Adds a fruit to the Fruit option and to Mixed. `draw(surface, x, y, r)` paints
the fruit centred at `(x, y)` with radius `r`, using `pygame.draw`. It is
drawn large once per size and scaled down, so edges come out smooth. `color`
is used for the particles when the fruit is eaten.

### `api.add_sound(name, filename)`

Registers a sound file shipped in the mod's folder. To play it, add an event to
the game: `game.events.append(api.game.Event("my_sound"))`. Registering a
built-in name such as `"eat"` replaces that sound (an asset pack still wins).

### Other API members

| Member | What it is |
| --- | --- |
| `api.name` | The mod's name (file or folder name) |
| `api.folder` | The folder the mod lives in |
| `api.asset("file.png")` | Path to a file in the mod's folder |
| `api.log(...)` | Print a message to the terminal, prefixed with the mod's name |
| `api.game` | The `opensnake.game` module: `Event`, `Wall`, `Item`, `Apple`, `Seg`, `DIRS`, ... |
| `api.render` | The `opensnake.render` module: drawing helpers such as `aa_disc`, `bezier`, `ellipse_poly`, `mix` |
| `api.api_version` | Currently `1` |

### The game object

Useful parts of the `Game` passed to hooks (see `opensnake/game.py`):

| Attribute / method | Meaning |
| --- | --- |
| `w`, `h` | Board size in cells |
| `tick`, `score` | Moves made and fruit eaten this game |
| `snakes` | List of snakes (two in Yin Yang). `snake.body` is a list of `Seg(x, y)`, head first; `snake.dir` is `"up"`/`"down"`/`"left"`/`"right"`; `snake.grow` is segments still to add; `snake.shield` is shields held |
| `apples` | Fruit on the board (`x`, `y`, `fruit`, `poison`, `locked`) |
| `walls` | Dict of `(x, y)` to `Wall(x, y, kind)` |
| `items`, `mines`, `arrows`, `gates`, `targets` | Other board objects |
| `events` | List of `Event`s; append one to play a sound by name |
| `mod_state` | A dict mods can store anything in; cleared each new game |
| `rng` | The game's random number generator; use it instead of `random` |
| `over`, `won` | Set `over = True` (and `snake.dead = True`) to end the game |
| `has(mode_id)` | Whether a mode is on |
| `solid_at(x, y)` | What would stop a head at `(x, y)`, or `None` |
| `is_free(x, y)` | Whether a cell is completely empty |
| `random_free()`, `random_free(ok)` | A random empty cell (or `None` if the board is full), optionally filtered by a function `ok(x, y)` |
| `spawn_wall()`, `spawn_mine()`, `spawn_gate()`, `spawn_arrow()`, `spawn_shield()` | Add hazards and items away from the snake's head |
| `fill_apples()` | Top the fruit back up to the chosen count |

### The view (for `draw`)

`draw(surface, game, view)` draws onto the visible part of the board. On big
boards that is only a window onto the board, so convert cell positions with
the view:

| Member | Meaning |
| --- | --- |
| `view.c` | Cell size in pixels |
| `view.w`, `view.h` | Viewport size in pixels |
| `view.px(x, y)` | Top-left pixel of cell `(x, y)` |
| `view.center(x, y)` | Centre pixel of cell `(x, y)` |
| `view.visible(x, y)` | Whether cell `(x, y)` is on screen (skip drawing it if not) |
| `view.now` | Milliseconds since start, for animation |

## For developers

### Code layout

| File | Contents |
| --- | --- |
| `opensnake/game.py` | Game rules and simulation. No pygame, easy to test. |
| `opensnake/modes.py` | Mode list, conflicts, speed curve, board limits, options. |
| `opensnake/speedrun.py` | Speedrun categories, timer, replays, `--verify` and world records. |
| `opensnake/server.py` | The OpenSnake server: website, accounts, site records and versus matches. |
| `opensnake/net.py` | Talking to a server from the desktop game or the browser. |
| `opensnake/online.py` | The Online screen, lobby and versus match screens. |
| `opensnake/records.json` | Speedrun world records. |
| `opensnake/render.py` | All drawing: board, fruit, snake path, objects, mode icons, the scrolling view. |
| `opensnake/audio.py` | Sound loading and synthesis. |
| `opensnake/sounds/` | Bundled sound recordings (see CREDITS.md). |
| `opensnake/images/` | Bundled SVG artwork (see CREDITS.md). |
| `opensnake/assets.py` | Asset pack loading. |
| `opensnake/addons.py` | Finding resource packs and mods for the Packs & Mods screen. |
| `opensnake/packs/` | Built-in resource packs (Shadow Venom). |
| `opensnake/mods.py` | Mod loading and the mod API. |
| `opensnake/registry.py` | Hooks and sounds registered by mods. |
| `opensnake/app.py` | Window, game loop, menu, HUD, settings. |
| `examples/mods/` | Example mod. |
| `packaging/launcher.py` | Entry point for the standalone builds. |
| `packaging/linux/` | Desktop file, icons and install script for Linux. |
| `web-support/` | Browser version: build and local server scripts. See [web-support/README.md](web-support/README.md). |

### Building releases

Pushing a version tag builds everything on GitHub Actions
(`.github/workflows/release.yml`) and attaches the files to a **draft**
release, which you then review and publish:

```sh
git tag -a v0.2.0 -m "OpenSnake 0.2.0"
git push origin v0.2.0
```

Bump `version` in `pyproject.toml` and `__version__` in
`opensnake/__init__.py` first. To build a standalone game for your own system
locally:

```sh
pip install . pyinstaller
pyinstaller --onefile --windowed --name OpenSnake --paths . \
  --collect-submodules opensnake --collect-data opensnake packaging/launcher.py
```

The result is in `dist/`. (On macOS use `--onedir` instead of `--onefile` to
get an `.app`.) PyInstaller only builds for the system it runs on.

### Tests

```sh
python -m unittest discover tests
```

The tests cover each mode's rules, smooth movement through turns, huge and
rectangular boards, settings migration, mod loading (including broken mods),
and a fuzz test that plays random moves through every pair of modes. The
mod tests print tracebacks from deliberately broken test mods; that is
expected.

### Contributing

Pull requests are welcome. To add a built-in mode: add it to `MODES` in
`modes.py`, add its rules in `game.py` (check `self.has("yourmode")`), draw
anything new in `render.py`, add a menu icon in `mode_icon`, and add a test.
For something more experimental, consider writing it as a mod first.

## License

The code is BSD 3-Clause; see [LICENSE](LICENSE). The bundled Twemoji artwork
is CC-BY 4.0 and the eating sounds are CC0; see [CREDITS.md](CREDITS.md).
