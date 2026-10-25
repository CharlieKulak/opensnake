# Credits

OpenSnake's code is BSD 3-Clause licensed (see LICENSE). The bundled art and
sounds below come from other people and keep their own licenses.

## Images

The fruit, key, lock, shield, bomb (mine), rock (statue), skull and trophy
images in `opensnake/images/` are from **Twemoji**, copyright Twitter, Inc and
other contributors, licensed under
[CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/) (full text in
`opensnake/images/LICENSE-CC-BY-4.0.txt`).

- Source: <https://github.com/jdecked/twemoji>, commit
  `b6b55fef1e8636b540a6d016a4729ca8cdf2e60b`, `assets/svg/`
- Changes: files renamed to the sprite they are used for
  (e.g. `1f34e.svg` -> `fruit_apple.svg`). At run time the game renders them
  at board-cell size, adds coloured backdrops to keys and locks, and builds
  the poison fruit by tinting the apple purple and adding the skull.

| File | Twemoji code point |
| --- | --- |
| `fruit_apple.svg` | 1f34e |
| `fruit_orange.svg` | 1f34a |
| `fruit_cherry.svg` | 1f352 |
| `fruit_grape.svg` | 1f347 |
| `fruit_strawberry.svg` | 1f353 |
| `fruit_lemon.svg` | 1f34b |
| `fruit_banana.svg` | 1f34c |
| `key.svg` | 1f511 |
| `lock.svg` | 1f512 |
| `shield.svg` | 1f6e1 |
| `mine.svg` | 1f4a3 |
| `statue.svg` | 1faa8 |
| `skull.svg` | 2620 |
| `trophy.svg` | 1f3c6 |

Everything else on screen (board, snake, walls, gates, arrows, targets, mode
icons) is drawn in code. The OpenSnake logo (`opensnake/images/opensnake.svg`,
`packaging/linux/opensnake.svg`, `opensnake-256.png`) is original to this
project and BSD 3-Clause licensed like the code.

## Sounds

| File | Source | Author | License |
| --- | --- | --- | --- |
| `opensnake/sounds/eat_1.ogg` ... `eat_5.ogg` | ["7 Eating Crunches"](https://opengameart.org/content/7-eating-crunches) (`crunch.3.ogg` to `crunch.7.ogg`) | StarNinjas | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

All other sounds are synthesized in code (`opensnake/audio.py`).
