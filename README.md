
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
| B | | Random "Blender" mix of modes |
| M | Mute / unmute | |
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

**Width and Height.** The board size in cells. Any rectangle from 8 x 5 up to
1000 x 1000 works. Click the box and type a number, then press Enter (numbers
outside the range are clamped), or use the `<` `>` arrows / Left and Right
keys (hold Shift to change by 10).

Boards that fit the window are scaled to fill it. Bigger boards keep the cells
readable and **scroll**: the camera follows the snake, and markers at the
screen edge point to the nearest off-screen fruit with its distance in cells.

**Speed.** A slider with three marked stops:

| Stop | Time per cell | Cells per second |
| --- | --- | --- |
| Slow | 170 ms | 5.9 |
| Default | 130 ms | 7.7 |
| Fast | 85 ms | 11.8 |

Any position in between works too; the slider snaps to a stop when you get
close to it. The current speed in cells per second is shown on the right.

A best score is kept separately for every combination of modes, board size,
speed and fruit count.

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

Settings and best scores are saved automatically to:

- Linux: `~/.config/opensnake/settings.json`
- macOS: `~/Library/Application Support/OpenSnake/settings.json`
- Windows: `%APPDATA%\OpenSnake\settings.json`

Delete the file to reset everything. Settings files from older versions are
converted automatically.

## Asset packs

An asset pack is a folder of your own images, sounds and colours that replace
the built-in ones. Anything the pack doesn't provide uses the built-in
version, so a pack can be as small as one file.

OpenSnake looks for a pack in, in order:

1. the folder given with `opensnake --assets DIR`
2. the `OPENSNAKE_ASSETS` environment variable
3. an `assets` folder next to `settings.json` (see above)

Only use files you have the right to use. The `assets/` folder is in
`.gitignore` so a personal pack is not committed by accident.

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

Mods add new game modes, fruits and sounds, written in Python. A mod mode
shows up in the menu next to the built-in ones and can be mixed with them in
Blender.

> **Mods are ordinary Python code and can do anything a program on your
> computer can do. Only install mods from people you trust.**

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
| `opensnake/render.py` | All drawing: board, fruit, snake path, objects, mode icons, the scrolling view. |
| `opensnake/audio.py` | Sound loading and synthesis. |
| `opensnake/sounds/` | Bundled sound recordings (see CREDITS.md). |
| `opensnake/images/` | Bundled SVG artwork (see CREDITS.md). |
| `opensnake/assets.py` | Asset pack loading. |
| `opensnake/mods.py` | Mod loading and the mod API. |
| `opensnake/registry.py` | Hooks and sounds registered by mods. |
| `opensnake/app.py` | Window, game loop, menu, HUD, settings. |
| `examples/mods/` | Example mod. |
| `packaging/launcher.py` | Entry point for the standalone builds. |
| `packaging/linux/` | Desktop file, icons and install script for Linux. |

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
