"""Online play: the server connection, accounts, the versus lobby and matches.

The server is the website the browser game was loaded from, or (on the
desktop) an address typed on the Online screen. Logins are remembered: in the
browser's storage for that site, or in the desktop settings file per server.
"""

from __future__ import annotations

import urllib.parse

import pygame

from .game import DIRS, OPPOSITE, Game, apply_state
from .modes import MODE_NAMES
from .net import WEB, Request, Socket, page_origin, set_page_title, web_storage_get, web_storage_set, ws_url

# Must match opensnake/server.py (which can't be imported here: the browser build doesn't ship it).
VERSUS_MODES = ["wall", "borderless", "cheese", "poison", "portal", "shield", "magnet", "twin",
                "statue", "key", "light"]
SIZES = [("small", "Small 16x12"), ("medium", "Medium 20x16"), ("large", "Large 28x22")]
SPEEDS = [(0.25, "Slow"), (0.5, "Default"), (0.75, "Fast")]
FRUITS = [1, 3, 5]
GOALS = [(0, "Last snake alive"), (10, "First to 10"), (20, "First to 20"), (30, "First to 30")]

TEAM_NAMES = ["Blue", "Orange"]
TEAM_UI = [(61, 111, 232), (232, 112, 26)]
TEAM_COLORS = [  # (head, tail) per player within a team
    [((61, 111, 232), (122, 162, 255)), ((20, 150, 200), (110, 210, 240)),
     ((90, 70, 220), (160, 150, 255)), ((30, 120, 160), (110, 190, 220))],
    [((232, 112, 26), (255, 179, 107)), ((210, 50, 60), (255, 140, 140)),
     ((220, 160, 20), (255, 215, 110)), ((200, 60, 140), (250, 150, 200))],
]

WHITE = (255, 255, 255)
INK = (40, 52, 33)
MUTED = (96, 112, 86)
ACCENT = (61, 111, 232)
GOOD = (40, 160, 70)
BAD = (210, 60, 50)
FIELD_BG = (242, 244, 239)


class Field:
    """A one-line text box."""

    def __init__(self, label: str, value: str = "", masked: bool = False, max_len: int = 40,
                 upper: bool = False, allowed: str | None = None):
        self.label, self.value, self.masked = label, value, masked
        self.max_len, self.upper, self.allowed = max_len, upper, allowed
        self.rect = pygame.Rect(0, 0, 0, 0)

    def type(self, ch: str) -> None:
        if self.upper:
            ch = ch.upper()
        if ch and ch.isprintable() and len(self.value) < self.max_len and \
                (self.allowed is None or ch in self.allowed):
            self.value += ch


class Online:
    def __init__(self, app):
        self.app = app
        settings = app.settings
        self.server = page_origin() if WEB else settings.get("server_url", "")
        self.server_state = "none"   # none / checking / ok / no-server / error
        self.server_note = ""
        self.user = ""
        self.token = ""
        self.message, self.message_color = "", MUTED
        self.requests: list[tuple[Request, object]] = []
        ok_name = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        self.fields = {
            "server": Field("Server", self.server, max_len=120),
            "username": Field("Username", max_len=20, allowed=ok_name),
            "password": Field("Password", masked=True, max_len=64),
            "code": Field("Code", max_len=4, upper=True, allowed="ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        }
        self.focus: str | None = None
        self.hits: list[tuple[pygame.Rect, object]] = []
        # versus
        self.sock: Socket | None = None
        self.outbox: list[dict] = []
        self.my_id = None
        self.my_name = ""
        self.room: dict | None = None
        self.game: Game | None = None
        self.you = -1
        self.tick_ms = 130.0
        self.countdown: int | None = None
        self.result: dict | None = None
        # Turns we've sent but the server hasn't applied yet: [(direction, sent_at_ms)].
        # They're shown on our own snake straight away (client-side prediction).
        self.pending: list[tuple[str, int]] = []
        self.ping_ms: float | None = None  # round trip to the server, shown in matches
        self.last_ping = 0
        self.load_login()
        if self.server:
            self.check_server()

    # ---- login storage --------------------------------------------------------------

    def load_login(self) -> None:
        if WEB:
            self.user, self.token = web_storage_get("opensnake_user"), web_storage_get("opensnake_token")
        else:
            acct = self.app.settings.get("accounts", {}).get(self.server) or {}
            self.user, self.token = acct.get("user", ""), acct.get("token", "")

    def save_login(self, user: str, token: str) -> None:
        self.user, self.token = user, token
        if WEB:
            web_storage_set("opensnake_user", user)
            web_storage_set("opensnake_token", token)
        else:
            accounts = self.app.settings.setdefault("accounts", {})
            if token:
                accounts[self.server] = {"user": user, "token": token}
            else:
                accounts.pop(self.server, None)
            self.app.store.save()

    @property
    def logged_in(self) -> bool:
        return bool(self.token) and self.server_state == "ok"

    @property
    def site(self) -> str:
        return urllib.parse.urlparse(self.server).netloc or self.server

    # ---- requests -----------------------------------------------------------------------

    def request(self, method, path, body=None, then=None, auth=True):
        req = Request(method, self.server.rstrip("/") + path, body, self.token if auth else None)
        self.requests.append((req, then))
        return req

    def say(self, text: str, color=MUTED) -> None:
        self.message, self.message_color = text, color

    def check_server(self) -> None:
        if not self.server:
            self.server_state = "none"
            return
        self.server_state, self.server_note = "checking", "Connecting..."

        def done(r):
            if r.ok and r.data.get("server") == "OpenSnake":
                self.server_state = "ok"
                self.server_note = f"Connected to {self.site} (server {r.data.get('version', '?')})"
                if self.token:
                    self.request("GET", "/api/me", then=self._me)
                self.fetch_records()
            elif r.status in (404, 405) or (r.ok and r.data.get("server") != "OpenSnake"):
                self.server_state = "no-server"
                self.server_note = ("This website doesn't run the OpenSnake server, so online play, "
                                    "accounts and site records aren't available here.")
            else:
                self.server_state, self.server_note = "error", r.message
        self.request("GET", "/api/info", then=done, auth=False)

    def _me(self, r):
        if r.ok:
            self.user = r.data.get("username", self.user)
        elif r.status == 401:  # login expired or the server was reset
            self.save_login("", "")
            self.say("Your saved login is no longer valid. Please log in again.", BAD)

    def fetch_records(self) -> None:
        def done(r):
            if r.ok and isinstance(r.data.get("records"), dict):
                self.app.records.set_server(r.data["records"], self.site)
        self.request("GET", "/api/records", then=done, auth=False)

    def connect(self) -> None:
        url = self.fields["server"].value.strip().rstrip("/")
        if url and "://" not in url:
            url = "http://" + url
        self.server = url
        self.fields["server"].value = url
        self.app.settings["server_url"] = url
        self.app.store.save()
        self.load_login()
        self.app.records.clear_server()
        self.check_server()

    def login(self, create: bool) -> None:
        name, pw = self.fields["username"].value.strip(), self.fields["password"].value
        if not name or not pw:
            self.say("Type a username and password first.", BAD)
            return

        def done(r):
            if r.ok:
                self.save_login(r.data["username"], r.data["token"])
                self.fields["password"].value = ""
                self.say(("Account created. " if create else "") + f"Logged in as {self.user}.", GOOD)
                self.fetch_records()
            else:
                self.say(r.message, BAD)
        self.say("Creating account..." if create else "Logging in...")
        self.request("POST", "/api/register" if create else "/api/login",
                     {"username": name, "password": pw}, then=done, auth=False)

    def logout(self) -> None:
        if self.token:
            self.request("POST", "/api/logout", {})
        self.save_login("", "")
        self.say("Logged out.")

    def submit_run(self, run_json: dict, report) -> None:
        """Send a finished speedrun to this site's leaderboard; report(text, color) with the outcome."""
        def done(r):
            if not r.ok:
                report(f"Not submitted: {r.message}", BAD)
            elif not r.data.get("valid"):
                report("The server couldn't verify this run.", BAD)
            elif r.data.get("wr"):
                report(f"New world record on {self.site}!", GOOD)
            elif r.data.get("pb"):
                report(f"Submitted: #{r.data.get('rank')} on {self.site}", GOOD)
            else:
                report(f"Submitted to {self.site} (not your best there)", MUTED)
            self.fetch_records()
        report(f"Submitting to {self.site}...", MUTED)
        self.request("POST", "/api/runs", run_json, then=done)

    # ---- per-frame ------------------------------------------------------------------------

    def _ping(self) -> None:
        now = pygame.time.get_ticks()
        if self.sock and self.sock.state == "open" and now - self.last_ping > 2000:
            self.last_ping = now
            self.sock.send({"t": "ping", "at": now})

    def poll(self) -> None:
        self._ping()
        for req, then in list(self.requests):
            if req.poll():
                self.requests.remove((req, then))
                if then:
                    then(req)
        if self.sock:
            if self.sock.state == "open" and self.outbox:
                for m in self.outbox:
                    self.sock.send(m)
                self.outbox.clear()
            msgs = self.sock.poll()
            # If several game states arrived since last frame (slow device, busy
            # network), only draw the newest; keep the sounds/effects of the rest.
            states = [i for i, m in enumerate(msgs) if m.get("t") == "state"]
            carried = []
            for i, msg in enumerate(msgs):
                if msg.get("t") == "state" and states and i != states[-1]:
                    carried += msg["s"].get("events", [])
                    continue
                if carried and msg.get("t") == "state":
                    msg["s"]["events"] = carried + msg["s"].get("events", [])
                self.on_message(msg)
            if self.sock.state in ("closed", "error"):
                lost = self.sock.state == "error" or self.room is not None
                self.sock = None
                self.room = None
                if lost:
                    self.say("Couldn't connect to the match server." if self.my_id is None
                             else "Disconnected from the match.", BAD)
                if self.app.state in ("lobby", "versus"):
                    self.app.state = "online"

    def send(self, msg: dict) -> None:
        if not self.sock:
            query = {"token": self.token} if self.token else {"name": self.fields["username"].value.strip()}
            self.sock = Socket(ws_url(self.server) + "?" + urllib.parse.urlencode(query))
            self.my_id = None
        if self.sock.state == "open":
            self.sock.send(msg)
        else:
            self.outbox.append(msg)

    def on_message(self, m: dict) -> None:
        t = m.get("t")
        app = self.app
        if t == "welcome":
            self.my_id, self.my_name = m["id"], m["name"]
        elif t == "error":
            self.say(m.get("msg", "Error"), BAD)
        elif t == "room":
            if not self.room or self.room.get("code") != m["code"]:
                set_page_title(f"OpenSnake - match {m['code']}")
            self.room = m
            if m["state"] == "lobby" and app.state != "lobby":
                app.state = "lobby"
                self.result = None
                self.say("")
        elif t == "start":
            g = Game(8, 5)
            apply_state(g, m["state"])
            self._colour(g)
            self.game, self.you, self.tick_ms = g, m["you"], float(m["tick_ms"])
            self.countdown, self.result = 3, None
            self.pending = []
            app.game = g
            app.acc = 0.0
            app.state = "versus"
            app.renderer.particles.clear()
        elif t == "countdown":
            self.countdown = m["n"] or None
            app.sfx.play("start" if not m["n"] else "turn")
        elif t == "state" and self.game:
            apply_state(self.game, m["s"])
            self._colour(self.game)
            self._predict()
            app.acc = 0.0
            app.drain()
        elif t == "pong" and isinstance(m.get("at"), (int, float)):
            rtt = pygame.time.get_ticks() - m["at"]
            self.ping_ms = rtt if self.ping_ms is None else 0.7 * self.ping_ms + 0.3 * rtt
        elif t == "over":
            self.result = m
            mine = self.game.snakes[self.you].team if self.game and 0 <= self.you < len(self.game.snakes) else -1
            app.sfx.play("win" if m.get("winner") == mine else "die")

    @staticmethod
    def _colour(g: Game) -> None:
        count = [0, 0]
        for s in g.snakes:
            if s.colors is None:
                s.colors = TEAM_COLORS[s.team][count[s.team] % 4]
            count[s.team] += 1

    # ---- actions --------------------------------------------------------------------------

    def host(self) -> None:
        if self.server_state != "ok":
            self.say("Connect to a server first.", BAD)
            return
        self.say("Creating a match...")
        self.send({"t": "host", "settings": {"size": "medium", "speed": 0.5, "apples": 3, "goal": 0, "modes": []}})

    def join(self) -> None:
        code = self.fields["code"].value.strip().upper()
        if self.server_state != "ok":
            self.say("Connect to a server first.", BAD)
        elif len(code) != 4:
            self.say("Match codes are 4 letters.", BAD)
        else:
            self.say(f"Joining {code}...")
            self.send({"t": "join", "code": code})

    def leave(self) -> None:
        if self.sock:
            self.send({"t": "leave"})
        set_page_title("OpenSnake")
        self.room = None
        self.game = None
        self.app.game = None
        self.app.new_game()
        self.app.state = "online"

    def is_host(self) -> bool:
        return bool(self.room) and self.room["host"] == self.my_id

    def my_team(self) -> int:
        for p in (self.room or {}).get("players", []):
            if p["id"] == self.my_id:
                return p["team"]
        return 0

    def change(self, key, value) -> None:
        if self.is_host():
            # Update our copy straight away so quick successive changes build on each other;
            # the server's next room update confirms (or corrects) it.
            self.room["settings"] = {**self.room["settings"], key: value}
            self.send({"t": "settings", "settings": self.room["settings"]})

    def toggle_mode(self, mode) -> None:
        modes = list(self.room["settings"]["modes"])
        modes.remove(mode) if mode in modes else modes.append(mode)
        self.change("modes", modes)

    # ---- input ------------------------------------------------------------------------------

    def key(self, ev) -> None:
        """Keys on the Online and Lobby screens."""
        if self.focus and self.app.state == "online":
            f = self.fields[self.focus]
            if ev.key == pygame.K_BACKSPACE:
                f.value = f.value[:-1]
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.submit_focus()
            elif ev.key == pygame.K_TAB:
                self.next_field(-1 if ev.mod & pygame.KMOD_SHIFT else 1)
            elif ev.key == pygame.K_ESCAPE:
                self.focus = None
            elif ev.key == pygame.K_v and ev.mod & pygame.KMOD_CTRL:
                self.paste(f)
            elif ev.unicode:
                f.type(ev.unicode)
            return
        if ev.key == pygame.K_ESCAPE:
            if self.app.state == "lobby":
                self.leave()
            else:
                self.app.open_menu()
        elif ev.key == pygame.K_TAB and self.app.state == "online":
            self.next_field(1)
        elif ev.key == pygame.K_h and self.app.state == "online":
            self.host()
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.app.state == "lobby" and self.is_host():
            self.send({"t": "start"})

    def paste(self, f: Field) -> None:
        try:
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            text = pygame.scrap.get_text() or ""
        except Exception:
            text = ""
        for ch in text.strip():
            f.type(ch)

    def visible_fields(self) -> list[str]:
        keys = [] if WEB else ["server"]
        if not self.logged_in:
            keys += ["username", "password"]
        return keys + ["code"]

    def next_field(self, step: int) -> None:
        keys = self.visible_fields()
        i = keys.index(self.focus) if self.focus in keys else -1
        self.focus = keys[(i + step) % len(keys)]

    def submit_focus(self) -> None:
        if self.focus == "server":
            self.connect()
        elif self.focus in ("username", "password"):
            self.login(create=False)
        elif self.focus == "code":
            self.join()

    def _my_snake(self):
        g = self.game
        return g.snakes[self.you] if g and 0 <= self.you < len(g.snakes) else None

    def _predict(self) -> None:
        """Show our not-yet-applied turn on our own snake, so it reacts instantly."""
        me = self._my_snake()
        if not me or me.dead:
            self.pending = []
            return
        now = pygame.time.get_ticks()
        if self.pending and me.dir == self.pending[0][0]:
            self.pending.pop(0)  # the server has applied it
        # Drop turns the server evidently didn't take (e.g. an illegal reverse).
        self.pending = [(d, at) for d, at in self.pending if now - at < 3 * self.tick_ms + 250]
        if self.pending:
            me.planned = self.pending[0][0]  # the renderer curves the head this way

    def turn(self, d: str) -> None:
        me = self._my_snake()
        if not me or me.dead or self.game.over:
            return
        last = self.pending[-1][0] if self.pending else me.dir
        if d in (last, OPPOSITE[last]) or d not in DIRS or len(self.pending) >= 2:
            return  # same as the server would ignore
        self.send({"t": "input", "d": d})
        self.pending.append((d, pygame.time.get_ticks()))
        self._predict()
        self.app.sfx.play("turn")

    def versus_key(self, ev) -> None:
        from .app import KEYMAP
        if ev.key in KEYMAP:
            if self.game and not self.game.over:
                self.turn(KEYMAP[ev.key])
        elif ev.key in (pygame.K_q, pygame.K_ESCAPE) and (self.result or ev.key == pygame.K_q):
            self.leave()
        elif ev.key in (pygame.K_RETURN, pygame.K_SPACE) and self.result and self.is_host():
            self.send({"t": "rematch"})

    def click(self, pos) -> None:
        self.focus = None
        for rect, action in self.hits:
            if rect.collidepoint(pos):
                action()
                return

    # ---- drawing helpers ------------------------------------------------------------------------

    def _panel(self):
        app = self.app
        scr = app.screen
        shade = pygame.Surface(scr.get_size(), pygame.SRCALPHA)
        shade.fill((20, 35, 12, 150))
        scr.blit(shade, (0, 0))
        sw, sh = scr.get_size()
        grow = max(1.0, min(sw / 1000, sh / 840))
        pw, ph = min(sw - 40, round(940 * grow)), min(sh - 40, round(800 * grow))
        p = pygame.Rect((sw - pw) // 2, (sh - ph) // 2, pw, ph)
        pygame.draw.rect(scr, WHITE, p, border_radius=18)
        self.hits = []
        return p, grow

    def _text(self, text, size, color, **pos):
        img = self.app.renderer.font(max(10, int(size))).render(text, True, color)
        self.app.screen.blit(img, img.get_rect(**pos))
        return img.get_rect(**pos)

    def _button(self, rect, text, action, primary=False, enabled=True):
        scr = self.app.screen
        bg = (ACCENT if primary else (232, 236, 228)) if enabled else (225, 228, 222)
        pygame.draw.rect(scr, bg, rect, border_radius=rect.h // 2)
        f = self.app.renderer.font(int(rect.h * 0.48))
        img = f.render(text, True, (WHITE if primary else INK) if enabled else (160, 166, 156))
        if img.get_width() > rect.w - 14:
            img = pygame.transform.smoothscale(img, (rect.w - 14, max(1, int(img.get_height() * (rect.w - 14) / img.get_width()))))
        scr.blit(img, img.get_rect(center=rect.center))
        if enabled:
            self.hits.append((rect, action))

    def _field(self, key, rect):
        f = self.fields[key]
        f.rect = rect
        scr = self.app.screen
        focused = self.focus == key
        pygame.draw.rect(scr, WHITE if focused else FIELD_BG, rect, border_radius=8)
        pygame.draw.rect(scr, ACCENT if focused else (200, 206, 194), rect, 2, border_radius=8)
        shown = "•" * len(f.value) if f.masked else f.value
        font = self.app.renderer.font(int(rect.h * 0.5), False)
        if not shown and not focused:
            img = font.render(f.label, True, (170, 176, 166))
        else:
            caret = "|" if focused and (pygame.time.get_ticks() // 500) % 2 == 0 else ""
            img = font.render(shown + caret, True, INK)
            if img.get_width() > rect.w - 16:  # show the end of long text
                img = img.subsurface((img.get_width() - (rect.w - 16), 0, rect.w - 16, img.get_height()))
        scr.blit(img, img.get_rect(midleft=(rect.x + 10, rect.centery)))
        self.hits.append((rect, lambda k=key: setattr(self, "focus", k)))

    # ---- Online screen ----------------------------------------------------------------------------

    def draw_online(self) -> None:
        p, grow = self._panel()
        ph, pw = p.h, p.w
        focus = self.focus  # clicks reset focus; keep it while drawing
        self._text("Online", ph * 0.07, (74, 117, 44), midtop=(p.centerx, p.y + ph * 0.025))
        x, w = p.x + 40, pw - 80
        row = max(34, int(ph * 0.055))
        y = p.y + int(ph * 0.13)
        sec = ph * 0.034

        # server
        self._text("Server", sec, INK, topleft=(x, y))
        y += sec + 8
        if WEB:
            self._text(f"This website: {self.site}", ph * 0.026, INK, topleft=(x, y))
            y += ph * 0.035
        else:
            self._field("server", pygame.Rect(x, y, int(w * 0.72), row))
            self._button(pygame.Rect(x + int(w * 0.75), y, int(w * 0.25), row), "Connect", self.connect, True)
            y += row + 6
        color = {"ok": GOOD, "error": BAD, "no-server": BAD}.get(self.server_state, MUTED)
        note = self.server_note or ("Type the address of an OpenSnake website, e.g. "
                                    "https://snake.example.com, and press Connect." if not WEB else "")
        self._text(note, ph * 0.023, color, topleft=(x, y))
        y += ph * 0.05

        # account
        self._text("Account", sec, INK, topleft=(x, y))
        y += sec + 8
        if self.logged_in:
            self._text(f"Logged in as {self.user} on {self.site}", ph * 0.028, GOOD, topleft=(x, y + 6))
            self._button(pygame.Rect(x + int(w * 0.75), y, int(w * 0.25), row), "Log out", self.logout)
            y += row + 6
            self._text("Your speedrun times are submitted to this site's leaderboard automatically.",
                       ph * 0.022, MUTED, topleft=(x, y))
            y += ph * 0.05
        else:
            half = int(w * 0.36)
            self._field("username", pygame.Rect(x, y, half, row))
            self._field("password", pygame.Rect(x + half + 10, y, half, row))
            bx = x + 2 * half + 20
            bw = (x + w - bx - 10) // 2
            ok = self.server_state == "ok"
            self._button(pygame.Rect(bx, y, bw, row), "Log in", lambda: self.login(False), True, ok)
            self._button(pygame.Rect(bx + bw + 10, y, bw, row), "Create account", lambda: self.login(True), False, ok)
            y += row + 6
            self._text("Log in to put your speedruns on this site's leaderboard. You stay logged in on this "
                       + ("browser." if WEB else "computer."), ph * 0.022, MUTED, topleft=(x, y))
            y += ph * 0.05

        # versus
        self._text("Versus (1v1 up to 4v4)", sec, INK, topleft=(x, y))
        y += sec + 8
        ok = self.server_state == "ok"
        self._button(pygame.Rect(x, y, int(w * 0.3), row), "Host a match", self.host, True, ok)
        cx = x + int(w * 0.36)
        self._text("or join with a code:", ph * 0.026, MUTED, midleft=(cx, y + row / 2))
        self._field("code", pygame.Rect(cx + int(w * 0.25), y, int(w * 0.17), row))
        self._button(pygame.Rect(x + int(w * 0.8), y, int(w * 0.2), row), "Join", self.join, False, ok)
        y += row + 6
        name_hint = (f"You'll play as {self.user}." if self.logged_in else
                     "Not logged in: you'll play as a guest" +
                     (f" named {self.fields['username'].value}." if self.fields["username"].value else "."))
        self._text(name_hint, ph * 0.022, MUTED, topleft=(x, y))

        if self.message:
            self._text(self.message, ph * 0.028, self.message_color, midbottom=(p.centerx, p.bottom - ph * 0.13))
        bh = max(34, int(ph * 0.055))
        self._button(pygame.Rect(p.centerx - int(70 * grow), p.bottom - int(ph * 0.05) - bh, int(140 * grow), bh),
                     "Back", self.app.open_menu)
        self._text("Tab: next box   Enter: confirm   H: host a match   Esc: back", ph * 0.022, MUTED,
                   midbottom=(p.centerx, p.bottom - 8))
        self.focus = focus

    # ---- Lobby ----------------------------------------------------------------------------------

    def draw_lobby(self) -> None:
        p, grow = self._panel()
        room = self.room
        if not room:
            return
        ph, pw = p.h, p.w
        host = self.is_host()
        self._text("Match code", ph * 0.03, MUTED, midtop=(p.centerx, p.y + ph * 0.025))
        self._text(room["code"], ph * 0.1, INK, midtop=(p.centerx, p.y + ph * 0.06))
        self._text("Share this code so others can join from the Online screen.", ph * 0.024, MUTED,
                   midtop=(p.centerx, p.y + ph * 0.165))

        # teams
        top = p.y + int(ph * 0.22)
        col_w = (pw - 100) // 2
        row_h = max(30, int(ph * 0.05))
        for team in (0, 1):
            x = p.x + 40 + team * (col_w + 20)
            members = [pl for pl in room["players"] if pl["team"] == team]
            self._text(f"{TEAM_NAMES[team]} team  ({len(members)}/4)", ph * 0.032, TEAM_UI[team], topleft=(x, top))
            for j in range(4):
                r = pygame.Rect(x, top + ph * 0.05 + j * (row_h + 6), col_w, row_h)
                pygame.draw.rect(self.app.screen, (244, 246, 241), r, border_radius=8)
                if j < len(members):
                    pl = members[j]
                    name = pl["name"] + ("  (you)" if pl["id"] == self.my_id else "") + \
                        ("  - host" if pl["id"] == room["host"] else "")
                    pygame.draw.circle(self.app.screen, TEAM_COLORS[team][j][0], (r.x + 16, r.centery), r.h * 0.22)
                    self._text(name, row_h * 0.5, INK, midleft=(r.x + 32, r.centery))
                else:
                    self._text("empty", row_h * 0.42, (170, 176, 166), midleft=(r.x + 32, r.centery))
        y = top + ph * 0.05 + 4 * (row_h + 6) + 6
        bw = int(200 * grow)
        self._button(pygame.Rect(p.centerx - bw // 2, y, bw, row_h), "Switch team",
                     lambda: self.send({"t": "team", "team": 1 - self.my_team()}))
        y += row_h + int(ph * 0.03)

        # settings
        s = room["settings"]
        self._text("Settings" + ("" if host else "  (the host chooses)"), ph * 0.032, INK, topleft=(p.x + 40, y))
        y += ph * 0.05
        x, w = p.x + 40, pw - 80
        opts = [
            ("Board", SIZES, s["size"], "size"),
            ("Speed", SPEEDS, s["speed"], "speed"),
            ("Fruit", [(n, str(n)) for n in FRUITS], s["apples"], "apples"),
            ("Win", GOALS, s["goal"], "goal"),
        ]
        cw = (w - 30) // 4
        for i, (label, choices, value, key) in enumerate(opts):
            r = pygame.Rect(x + i * (cw + 10), y, cw, row_h)
            pygame.draw.rect(self.app.screen, (244, 246, 241), r, border_radius=8)
            values = [c[0] for c in choices]
            idx = values.index(value) if value in values else 0
            text = dict(choices)[values[idx]]
            self._text(label, row_h * 0.38, MUTED, midtop=(r.centerx, r.y - row_h * 0.5))
            self._text(text, row_h * 0.45, INK, center=r.center)
            if host:
                self.hits.append((r, lambda k=key, v=values, n=idx: self.change(k, v[(n + 1) % len(v)])))
        y += row_h + ph * 0.025
        chip_w = (w - 10 * 5) // 6
        for i, mode in enumerate(VERSUS_MODES):
            r = pygame.Rect(x + (i % 6) * (chip_w + 10), y + (i // 6) * (row_h * 0.8 + 8), chip_w, int(row_h * 0.8))
            on = mode in s["modes"]
            pygame.draw.rect(self.app.screen, ACCENT if on else (236, 239, 232), r, border_radius=r.h // 2)
            self._text(MODE_NAMES.get(mode, mode), r.h * 0.5, WHITE if on else INK, center=r.center)
            if host:
                self.hits.append((r, lambda m=mode: self.toggle_mode(m)))

        if self.message:
            self._text(self.message, ph * 0.026, self.message_color, midbottom=(p.centerx, p.bottom - ph * 0.12))
        bh = max(34, int(ph * 0.06))
        by = p.bottom - int(ph * 0.045) - bh
        teams_ok = all(any(pl["team"] == t for pl in room["players"]) for t in (0, 1))
        if host:
            self._button(pygame.Rect(p.centerx - bw - 8, by, bw, bh), "Start match",
                         lambda: self.send({"t": "start"}), True, teams_ok)
        else:
            self._text("Waiting for the host to start...", ph * 0.028, MUTED, midright=(p.centerx - 16, by + bh / 2))
        self._button(pygame.Rect(p.centerx + 8, by, bw, bh), "Leave", self.leave)
        hint = "Click a setting to change it   Enter: start   Esc: leave" if host else "Esc: leave"
        self._text(hint, ph * 0.022, MUTED, midbottom=(p.centerx, p.bottom - 8))

    # ---- match ------------------------------------------------------------------------------------

    def draw_header(self, hh: int) -> None:
        app, g = self.app, self.game
        scr = app.screen
        f = app.renderer.font(int(hh * 0.5))
        small = app.renderer.font(int(hh * 0.34), False)
        for team in (0, 1):
            alive = sum(1 for s in g.snakes if s.team == team and not s.dead)
            total = sum(1 for s in g.snakes if s.team == team)
            text = f"{TEAM_NAMES[team]}  {g.team_score(team)}"
            img = f.render(text, True, WHITE)
            pos = {"midleft": (16, hh // 2)} if team == 0 else {"midright": (scr.get_width() - 16, hh // 2)}
            rect = img.get_rect(**pos)
            pygame.draw.rect(scr, TEAM_UI[team], rect.inflate(18, 8), border_radius=10)
            scr.blit(img, rect)
            sub = small.render(f"{alive}/{total} alive", True, (220, 236, 200))
            scr.blit(sub, sub.get_rect(midleft=(rect.right + 18, hh // 2)) if team == 0
                     else sub.get_rect(midright=(rect.left - 18, hh // 2)))
        mid = f"First to {g.goal}" if g.goal else "Last snake alive wins"
        me = g.snakes[self.you] if 0 <= self.you < len(g.snakes) else None
        if me and me.dead and not g.over:
            mid = "You're out - watching   Q: leave"
        if self.ping_ms is not None:
            mid += f"     ping {self.ping_ms:.0f} ms   {app.clock.get_fps():.0f} fps"
        img = small.render(mid, True, (220, 236, 200))
        scr.blit(img, img.get_rect(center=(scr.get_width() // 2, hh // 2)))

    def draw_overlay(self, rect: pygame.Rect, card) -> None:
        g = self.game
        if self.countdown:
            scr = self.app.screen
            big = self.app.renderer.font(int(rect.h * 0.3))
            cy = rect.centery - rect.h * 0.08
            shadow = big.render(str(self.countdown), True, (0, 0, 0))
            scr.blit(shadow, shadow.get_rect(center=(rect.centerx + 4, cy + 4)))
            img = big.render(str(self.countdown), True, WHITE)
            scr.blit(img, img.get_rect(center=(rect.centerx, cy)))
            if 0 <= self.you < len(g.snakes):  # which team you're on, in a pill under the number
                team = g.snakes[self.you].team
                label = self.app.renderer.font(int(rect.h * 0.045)).render(
                    f"You're on the {TEAM_NAMES[team]} team", True, WHITE)
                r = label.get_rect(midtop=(rect.centerx, cy + img.get_height() * 0.55))
                pygame.draw.rect(scr, TEAM_UI[team], r.inflate(28, 12), border_radius=(r.h + 12) // 2)
                scr.blit(label, r)
        elif self.result:
            w = self.result.get("winner")
            mine = g.snakes[self.you].team if 0 <= self.you < len(g.snakes) else -1
            title = "Draw!" if w is None else (f"{TEAM_NAMES[w]} team wins!")
            sub = "" if w is None else ("You win!" if w == mine else "You lose")
            a, b = self.result.get("scores", [0, 0])
            lines = [(title, 1.1, TEAM_UI[w] if w is not None else INK)]
            if sub:
                lines.append((sub, 0.7, GOOD if w == mine else BAD))
            lines.append((f"Fruit: {TEAM_NAMES[0]} {a} - {b} {TEAM_NAMES[1]}", 0.55, MUTED))
            buttons = [("Back to lobby", lambda: self.send({"t": "rematch"}), True)] if self.is_host() else []
            buttons.append(("Leave", self.leave, not buttons))
            if not self.is_host():
                lines.append(("Waiting for the host...", 0.5, MUTED))
            card(lines, buttons)

    def draw_labels(self, surf, view) -> None:
        """Player names above each snake's head."""
        g = self.game
        font = self.app.renderer.font(max(12, int(view.c * 0.42)))
        for i, s in enumerate(g.snakes):
            if s.dead or not s.body:
                continue
            name = "You" if i == self.you else s.name
            img = font.render(name, True, WHITE)
            x, y = view.center(s.head.x, s.head.y)
            r = img.get_rect(midbottom=(x, y - view.c * 0.55))
            bg = r.inflate(8, 2)
            pygame.draw.rect(surf, (*TEAM_UI[s.team],), bg, border_radius=bg.h // 2)
            surf.blit(img, r)
