"""The Online screen's account tabs: Profile, Friends, Store and Community.

Everything here talks to the site's OpenSnake server through the Online
object (requests, the login and its drawing helpers).
"""

from __future__ import annotations

import base64
import math
import random
import sys
import urllib.parse

import pygame

from . import cosmetics as cos
from .net import ImagePicker, decode_png, load_picture
from .online import ACCENT, BAD, GOOD, INK, MUTED, WHITE
from .speedrun import category_from_def, describe, format_time

CARD = (244, 246, 241)
POINTS = (214, 150, 0)

# The account screens and their tabs. Online and Store are reached from the
# menu's buttons; Community and Profile from the circles in its top corners.
SCREENS = {
    "online": [("play", "Play")],
    "community": [("community", "Categories"), ("ranking", "Leaderboard")],
    "profile": [("profile", "Profile"), ("friends", "Friends"), ("messages", "Messages")],
    "store": [("store", "Store")],
}
SCREEN_OF = {tab: screen for screen, tabs in SCREENS.items() for tab, _label in tabs}
TITLES = {"online": "Online", "community": "Community", "profile": "Profile", "store": "Store"}
STORE_TABS = [("shop", "Shop"), ("crates", "Loot boxes"), ("collection", "Collection")]

REEL_CARDS = 48       # cards on a loot box reel
REEL_WIN = 42         # where the prize sits on it
REEL_MS = 6200        # how long the spin takes


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 4


class Hub:
    def __init__(self, online):
        self.on = online
        self.viewing: dict | None = None   # another player's profile, on the Profile tab
        self.users: list[dict] = []
        self.users_query = None
        self.users_at = 0
        self.friends = {"friends": [], "incoming": [], "outgoing": []}
        self.friends_loaded = False
        self.community: list[dict] | None = None
        self.community_query = None
        self.community_at = 0
        self.store_tab = "shop"
        self.scroll = 0
        self.opening: dict | None = None   # the loot box being opened
        self.busy = False
        self.pictures: dict = {}           # player name -> [version, image or None while loading]
        self.picker: ImagePicker | None = None
        self.renaming: str | None = None   # id of the community category being renamed
        self.ranking: dict | None = None    # the community leaderboard, once loaded
        # messages
        self.chats: list[dict] = []        # conversations, newest first
        self.unread = 0
        self.chat_with: str | None = None  # the friend whose chat is open
        self.chat: list[dict] = []         # its messages, oldest first
        self.chat_more = False             # older messages to load
        self.chat_scroll = 0               # pixels scrolled up from the newest message
        self.chat_loading = False
        self.typing_path = False           # no file dialog here: type the picture's path instead

    @property
    def app(self):
        return self.on.app

    # ---- data ----------------------------------------------------------------------------

    def fields_for(self, tab: str) -> list[str]:
        return {"profile": ([] if self.viewing else ["bio"] + (["picture_path"] if self.typing_path else [])),
                "friends": ["users"],
                "messages": ["dm"] if self.chat_with else [],
                "community": ["community"] + (["rename"] if self.renaming else [])}.get(tab, [])

    def open_tab(self, tab: str) -> None:
        self.app.state = SCREEN_OF[tab]
        self.on.tab = tab
        self.on.focus = None
        self.scroll = 0
        self.on.say("")
        if tab == "profile":
            self.viewing = None
            self.on.refresh_me()
            self.on.fields["bio"].value = (self.on.me or {}).get("bio", "")
        elif tab == "friends":
            self.load_friends()
        elif tab == "store":
            self.on.refresh_me()
        elif tab == "community":
            self.load_community()
        elif tab == "ranking":
            self.load_ranking()
        elif tab == "messages":
            self.load_friends()
            self.load_chats()
            if self.chat_with:
                self.open_chat(self.chat_with)

    def load_friends(self) -> None:
        if not self.on.logged_in:
            return

        def done(r):
            if r.ok:
                self.friends = {k: r.data.get(k, []) for k in ("friends", "incoming", "outgoing")}
                self.friends_loaded = True
        self.on.request("GET", "/api/friends", then=done)

    def search_users(self) -> None:
        query = self.on.fields["users"].value.strip()
        self.users_query, self.users_at = query, pygame.time.get_ticks()
        if not query:
            self.users = []
            return

        def done(r, q=query):
            if r.ok and q == self.users_query:
                self.users = r.data.get("users", [])
        self.on.request("GET", "/api/users?" + urllib.parse.urlencode({"q": query}), then=done, auth=False)

    def load_ranking(self) -> None:
        def done(r):
            if r.ok:
                self.ranking = r.data
            else:
                self.on.say(r.message, BAD)
        self.on.request("GET", "/api/rankings", then=done)

    def load_community(self) -> None:
        query = self.on.fields["community"].value.strip()
        self.community_query, self.community_at = query, pygame.time.get_ticks()

        def done(r, q=query):
            if r.ok and q == self.community_query:
                self.community = r.data.get("categories", [])
                self.sync_names(self.community)
            elif not r.ok:
                self.community = []
                self.on.say(r.message, BAD)
        self.on.request("GET", "/api/categories?" + urllib.parse.urlencode({"q": query}), then=done, auth=False)

    # -- messages

    def load_chats(self) -> None:
        if not self.on.logged_in:
            return

        def done(r):
            if r.ok:
                self.chats = r.data.get("chats", [])
                self.unread = r.data.get("unread", 0)
        self.on.request("GET", "/api/messages", then=done)

    def message(self, name: str) -> None:
        """Open a chat with a friend from anywhere on the Online screen."""
        self.chat_with = None
        self.open_tab("messages")
        self.open_chat(name)

    def open_chat(self, name: str) -> None:
        self.chat_with, self.chat, self.chat_scroll, self.chat_more = name, [], 0, False
        self.on.fields["dm"].value = ""
        self.on.focus = "dm"
        for c in self.chats:
            if c["name"].lower() == name.lower():
                self.unread -= c.get("unread", 0)
                c["unread"] = 0
        self.load_messages()

    def load_messages(self, before: int | None = None) -> None:
        name = self.chat_with
        self.chat_loading = True

        def done(r):
            self.chat_loading = False
            if not r.ok or name != self.chat_with:
                return
            got = r.data.get("messages", [])
            self.chat_more = len(got) >= 50
            have = {m["id"] for m in self.chat}
            self.chat = [m for m in got if m["id"] not in have] + self.chat if before else got
        path = f"/api/messages/{urllib.parse.quote(name)}" + (f"?before={before}" if before else "")
        self.on.request("GET", path, then=done)

    def send_dm(self) -> None:
        body = self.on.fields["dm"].value.strip()
        if not body or not self.chat_with:
            return
        self.on.fields["dm"].value = ""

        def done(r):
            if r.ok:
                self.add_message(r.data)
            else:
                self.on.fields["dm"].value = body  # give it back to try again
                self.on.say(r.message, BAD)
        self.on.request("POST", "/api/messages", {"to": self.chat_with, "body": body}, then=done)

    def add_message(self, m: dict) -> None:
        if any(x["id"] == m["id"] for x in self.chat):
            return
        self.chat.append(m)
        self.chat_scroll = 0  # jump to the newest

    def on_dm(self, m: dict) -> None:
        """A message arrived (pushed by the server)."""
        me = self.on.user.lower()
        other = m["to"] if m["from"].lower() == me else m["from"]
        viewing = self.on.app.state == "profile" and self.on.tab == "messages" and \
            (self.chat_with or "").lower() == other.lower()
        if viewing:
            self.add_message(m)
            if m["from"].lower() != me:  # tell the server it's been read
                self.load_messages()
        elif m["from"].lower() != me:
            self.unread += 1
            text = m["body"] if len(m["body"]) <= 40 else m["body"][:39] + "..."
            self.on.toast(f"{m['from']}: {text}", ACCENT, 6000)
            self.app.sfx.play("turn")
        self.load_chats()

    def sync_names(self, entries) -> None:
        """Saved community categories take the name their creator has given them since."""
        from dataclasses import replace
        names = {e["id"]: e["name"] for e in entries}
        changed = False
        for i, c in enumerate(self.app.custom_cats):
            if c.id in names and c.name != names[c.id]:
                self.app.custom_cats[i] = replace(c, name=names[c.id])
                changed = True
        if changed:
            self.app.save_customs()

    def start_rename(self, entry: dict) -> None:
        self.renaming = entry["id"]
        self.on.fields["rename"].value = entry["name"]
        self.on.focus = "rename"

    def cancel_rename(self) -> None:
        self.renaming = None
        self.on.focus = None

    def save_rename(self) -> None:
        cid, name = self.renaming, self.on.fields["rename"].value.strip()

        def done(r):
            if r.ok:
                for e in self.community or []:
                    if e["id"] == cid:
                        e["name"] = r.data["name"]
                self.sync_names(self.community or [])
                self.on.say(f"Renamed to \"{r.data['name']}\".", GOOD)
                self.cancel_rename()
            else:
                self.on.say(r.message, BAD)
        self.on.request("POST", "/api/categories/rename", {"id": cid, "name": name}, then=done)

    def poll(self) -> None:
        """Search as you type (a moment after the last key), and finish choosing a picture."""
        if self.picker and self.picker.poll():
            picker, self.picker = self.picker, None
            if picker.state == "done":
                self.upload_picture(picker.data)
            elif picker.state == "no-dialog":
                self.typing_path = True
                self.on.focus = "picture_path"
                self.on.say("Type or paste the path to an image file, then press Enter.", MUTED)
            elif picker.state == "error":
                self.on.say(picker.error, BAD)
        now = pygame.time.get_ticks()
        if self.on.tab == "friends" and self.on.fields["users"].value.strip() != self.users_query \
                and now - self.users_at > 300:
            self.search_users()
        if self.on.tab == "community" and self.on.fields["community"].value.strip() != self.community_query \
                and now - self.community_at > 300:
            self.load_community()

    def view_profile(self, name: str) -> None:
        def done(r):
            if r.ok:
                self.viewing = r.data
                self.app.state, self.on.tab = "profile", "profile"
            else:
                self.on.say(r.message, BAD)
        self.on.request("GET", f"/api/users/{urllib.parse.quote(name)}", then=done)

    def friend(self, name: str, add: bool) -> None:
        def done(r):
            if r.ok:
                state = r.data.get("friend")
                self.on.say({"outgoing": f"Friend request sent to {name}.", "friends": f"You and {name} are friends!",
                             "none": ""}.get(state, ""), GOOD)
                if self.viewing and self.viewing.get("name") == name:
                    self.viewing["friend"] = state
                self.load_friends()
            else:
                self.on.say(r.message, BAD)
        self.on.request("POST", "/api/friends/add" if add else "/api/friends/remove", {"name": name}, then=done)

    def play_with(self, name: str) -> None:
        """Host a match and invite a friend to it."""
        self.on.invite_after_host = name
        self.on.host()

    # -- your own picture

    def choose_picture(self) -> None:
        self.on.say("Choose an image...", MUTED)
        self.picker = ImagePicker()

    def picture_from_path(self) -> None:
        try:
            data = load_picture(self.on.fields["picture_path"].value)
        except ValueError as e:
            self.on.say(str(e), BAD)
            return
        self.typing_path = False
        self.on.fields["picture_path"].value = ""
        self.upload_picture(data)

    def upload_picture(self, data: str) -> None:
        def done(r):
            if r.ok:
                self.on.set_me(r.data)
                self.pictures.pop(self.on.user.lower(), None)  # show the new one
                self.on.say("Picture saved.", GOOD)
            else:
                self.on.say(r.message, BAD)
        self.on.say("Uploading...", MUTED)
        self.on.request("POST", "/api/profile/picture", {"png": data}, then=done)

    def picture(self, name: str, version: str):
        """A player's own picture (downloaded once per version), or None while it loads."""
        key = name.lower()
        entry = self.pictures.get(key)
        if entry and entry[0] == version:
            return entry[1]
        self.pictures[key] = [version, None]

        def done(r):
            if r.ok and self.pictures.get(key, [None])[0] == version:
                try:
                    img = decode_png(base64.b64decode(r.data["png"]))
                    self.pictures[key][1] = img.convert_alpha() if pygame.display.get_surface() else img
                except Exception as e:  # a picture that won't load just isn't shown
                    print(f"Couldn't show {name}'s picture: {e}", file=sys.stderr)
        self.on.request("GET", f"/api/pictures/{urllib.parse.quote(name)}?v={version}", then=done, auth=False)
        return None

    def save_profile(self, **changes) -> None:
        def done(r):
            if r.ok:
                self.on.set_me(r.data)
                self.on.say("Saved.", GOOD)
            else:
                self.on.say(r.message, BAD)
        self.on.request("POST", "/api/profile", changes, then=done)

    def buy(self, item: str) -> None:
        def done(r):
            if r.ok:
                self.on.toast(f"Bought {cos.item_name(item)}!", GOOD)
                self.app.sfx.play("eat")
                self.on.refresh_me()
            else:
                self.on.say(r.message, BAD)
        self.on.request("POST", "/api/store/buy", {"item": item}, then=done)

    def open_crate(self, crate: cos.Crate) -> None:
        if self.busy or self.opening:
            return
        self.busy = True

        def done(r):
            self.busy = False
            if not r.ok:
                self.on.say(r.message, BAD)
                return
            if self.on.me:
                self.on.me["points"] = r.data.get("points", self.on.me.get("points", 0))
            rng = random.Random()
            reel = [cos.roll(crate, rng) for _ in range(REEL_CARDS)]
            reel[REEL_WIN] = r.data["item"]
            self.opening = {"crate": crate, "reel": reel, "result": r.data, "start": pygame.time.get_ticks(),
                            "land": rng.uniform(-0.38, 0.38), "last_card": -1, "done": False}
        self.on.say("")
        self.on.request("POST", "/api/store/open", {"crate": crate.id}, then=done)

    def finish_opening(self) -> None:
        self.opening = None
        self.on.refresh_me()

    def equip(self, skin_id: str) -> None:
        self.save_profile(skin=skin_id)

    def use_pack(self, pack_id: str) -> None:
        app = self.app
        app.refresh_packs()
        full = f"builtin:{pack_id}"
        if full in app.pack_by_id():
            packs = app.settings["packs"]
            if full in packs:
                packs.remove(full)
            else:
                packs.insert(0, full)
            app.store.save()
            app.apply_packs()

    def share_categories(self) -> None:
        listed = {c["id"] for c in self.community or []}
        mine = [c for c in self.app.custom_cats if c.id not in listed]
        if not mine:
            self.on.say("All your custom categories are already shared.", MUTED)
            return
        from .speedrun import category_def
        left = {"n": len(mine), "ok": 0}

        def done(r):
            left["n"] -= 1
            left["ok"] += bool(r.ok)
            if left["n"] == 0:
                self.on.say(f"Shared {left['ok']} categor{'y' if left['ok'] == 1 else 'ies'}.", GOOD)
                self.load_community()
        for c in mine:
            self.on.request("POST", "/api/categories", {"def": category_def(c)}, then=done)

    def save_category(self, entry: dict, play: bool) -> None:
        app = self.app
        try:
            cat = category_from_def({**entry["def"], "name": entry["name"]})
        except (KeyError, TypeError, ValueError):
            self.on.say("That category can't be played in this version.", BAD)
            return
        if not any(c.id == cat.id for c in app.custom_cats):
            app.custom_cats.append(cat)
            app.save_customs()
        if play:
            app.start_run(cat, "speedrun")
        else:
            self.on.say(f"Added \"{cat.name}\" to your Speedrun screen.", GOOD)

    # ---- input ------------------------------------------------------------------------------

    def wheel(self, dy: int) -> None:
        if self.on.tab == "messages" and self.chat_with:
            self.chat_scroll = max(0, self.chat_scroll + dy * 40)
            return
        self.scroll = max(0, self.scroll - dy)

    def key(self, ev) -> bool:
        """Keys on the account tabs (when not typing). True if handled."""
        if self.opening:
            if self.opening["done"] and ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
                self.finish_opening()
            return True
        if ev.key == pygame.K_ESCAPE and self.viewing:
            self.viewing = None
            return True
        if ev.key == pygame.K_ESCAPE and self.renaming:
            self.cancel_rename()
            return True
        if ev.key == pygame.K_ESCAPE and self.on.tab == "messages" and self.chat_with:
            self.chat_with = None
            return True
        if ev.key in (pygame.K_UP, pygame.K_DOWN):
            self.wheel(1 if ev.key == pygame.K_UP else -1)
            return True
        return False

    # ---- drawing helpers ------------------------------------------------------------------------

    def text(self, *args, **kw):
        return self.on._text(*args, **kw)

    def button(self, *args, **kw):
        return self.on._button(*args, **kw)

    def avatar(self, center, radius, value, name: str = "") -> None:
        scr = self.app.screen
        version = cos.custom_picture(value)
        if version and name:
            img = self.picture(name, version)
            pygame.draw.circle(scr, (220, 224, 216), center, radius)
            if img:
                d = max(2, int(radius * 2))
                round_img = pygame.transform.smoothscale(img, (d, d))
                mask = pygame.Surface((d, d), pygame.SRCALPHA)
                pygame.draw.circle(mask, (255, 255, 255, 255), (d / 2, d / 2), d / 2)
                round_img.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
                scr.blit(round_img, round_img.get_rect(center=center))
            return
        icon, ci = cos.parse_avatar(value)
        pygame.draw.circle(scr, cos.AVATAR_COLORS[ci], center, radius)
        img = self.app.renderer.sprites.image(icon, int(radius * 1.25))
        if img:
            scr.blit(img, img.get_rect(center=center))

    def rank_pill(self, rank: str, size: float, **pos) -> pygame.Rect:
        color = next((c for _lo, n, c in cos.RANKS if n == rank), (150, 160, 140))
        img = self.app.renderer.font(max(10, int(size))).render(rank, True, WHITE)
        r = img.get_rect(**pos)
        bg = r.inflate(int(size * 0.9), int(size * 0.35))
        bg.topleft = r.topleft
        r.center = bg.center
        pygame.draw.rect(self.app.screen, color, bg, border_radius=bg.h // 2)
        self.app.screen.blit(img, r)
        return bg

    def dot(self, center, online: bool) -> None:
        pygame.draw.circle(self.app.screen, (60, 190, 90) if online else (190, 196, 186), center, 5)

    def skin_preview(self, rect: pygame.Rect, skin: cos.Skin | None, now: float) -> None:
        """A little wiggling snake in a skin."""
        n = 7
        r = rect.h * 0.22
        outline = cos.skin_outline(skin, now) if skin else None
        pts = []
        for i in range(n):
            x = rect.right - r - i * (rect.w - 2 * r) / (n - 1)
            y = rect.centery + math.sin(now / 300 + i * 0.9) * rect.h * 0.18
            pts.append((i, x, y))
        for i, x, y in reversed(pts):
            col = cos.skin_color(skin, i, n, now) if skin else self.app_palette(i, n)
            if outline:
                pygame.draw.circle(self.app.screen, outline, (x, y), r + 2)
            pygame.draw.circle(self.app.screen, col, (x, y), r)
        _i, hx, hy = pts[0]
        for side in (-1, 1):
            pygame.draw.circle(self.app.screen, WHITE, (hx + r * 0.3, hy + side * r * 0.4), r * 0.3)
            pygame.draw.circle(self.app.screen, (30, 30, 30), (hx + r * 0.42, hy + side * r * 0.4), r * 0.15)

    def app_palette(self, i, n):
        from .modes import SNAKE_COLORS
        from .render import mix
        head, tail, _ = SNAKE_COLORS[self.app.settings["color"]]
        return mix(head, tail, i / max(1, n - 1))

    def item_art(self, rect: pygame.Rect, item: str, now: float) -> None:
        kind, _, key = item.partition(":")
        if kind == "skin":
            self.skin_preview(rect, cos.SKIN_BY_ID[key], now)
        else:
            pack = cos.PACK_BY_ID[key]
            w = rect.w // 3
            for i, col in enumerate(pack.swatch):
                pygame.draw.rect(self.app.screen, col, (rect.x + i * w, rect.y, w, rect.h),
                                 border_radius=6)

    def card(self, rect: pygame.Rect, item: str, now: float) -> None:
        rarity = cos.item_rarity(item)
        color = cos.RARITY_COLORS[rarity]
        scr = self.app.screen
        pygame.draw.rect(scr, CARD, rect, border_radius=10)
        pygame.draw.rect(scr, color, rect, 3, border_radius=10)
        art = pygame.Rect(rect.x + 10, rect.y + 8, rect.w - 20, int(rect.h * 0.45))
        self.item_art(art, item, now)
        name = cos.item_name(item)
        size = rect.h * 0.15
        while size > 9 and self.app.renderer.font(int(size)).size(name)[0] > rect.w - 12:
            size -= 1  # long names shrink to fit the card
        self.text(name, size, INK, midtop=(rect.centerx, art.bottom + 4))
        kind, _, key = item.partition(":")
        series = cos.SKIN_BY_ID[key].series if kind == "skin" else ""
        label = cos.RARITY_NAMES[rarity] + (f" · {series}" if series else "")
        self.text(label, rect.h * 0.12, color, midbottom=(rect.centerx, rect.bottom - 6))

    def points_badge(self, points: int, size: float, **pos) -> pygame.Rect:
        txt = f"{cos.format_points(points)} snake points"
        img = self.app.renderer.font(int(size)).render(txt, True, POINTS)
        r = img.get_rect(**pos)
        gem = r.h * 0.38
        cx, cy = r.x - gem - 6, r.centery
        pygame.draw.polygon(self.app.screen, POINTS, [(cx, cy - gem), (cx + gem, cy), (cx, cy + gem), (cx - gem, cy)])
        self.app.screen.blit(img, r)
        return r

    # ---- tabs ---------------------------------------------------------------------------------

    def tabs(self) -> list:
        return SCREENS.get(self.app.state, [])

    def draw_tabs(self, p, y) -> int:
        """The current screen's tab bar under the title (if it has more than one tab); returns its bottom."""
        tabs = self.tabs()
        if len(tabs) < 2:
            return y
        ph = p.h
        n = len(tabs)
        gap = 8
        tw = min((p.w - 80 - gap * (n - 1)) // n, int(p.w * 0.26))
        x0 = p.centerx - (n * tw + (n - 1) * gap) // 2
        th = max(30, int(ph * 0.048))
        for i, (tab, label) in enumerate(tabs):
            r = pygame.Rect(x0 + i * (tw + gap), y, tw, th)
            on = self.on.tab == tab
            pygame.draw.rect(self.app.screen, ACCENT if on else (236, 239, 232), r, border_radius=r.h // 2)
            self.text(label, th * 0.48, WHITE if on else INK, center=r.center)
            if tab == "messages" and self.unread > 0:  # unread badge
                c = (r.right - th * 0.3, r.y + th * 0.18)
                pygame.draw.circle(self.app.screen, BAD, c, th * 0.32)
                self.text(str(min(99, self.unread)), th * 0.34, WHITE, center=c)
            self.on.hits.append((r, lambda t=tab: self.open_tab(t)))
        return y + th

    def draw(self, p, top: int, bottom: int) -> None:
        tab = self.on.tab
        if tab not in ("community", "ranking") and not self.on.logged_in:
            what = {"store": "the store", "friends": "friends", "messages": "messages"}.get(tab, "your profile")
            mid = (top + bottom) // 2
            self.text(f"Log in to use {what}.", p.h * 0.034, INK, midbottom=(p.centerx, mid - 10))
            b = pygame.Rect(0, 0, int(p.w * 0.3), max(36, int(p.h * 0.058)))
            b.midtop = (p.centerx, mid + 10)
            self.button(b, "Log in on the Online screen", self.app.open_online, True)
            return
        if tab == "profile":
            self.draw_profile(p, top, bottom)
        elif tab == "friends":
            self.draw_friends(p, top, bottom)
        elif tab == "store":
            self.draw_store(p, top, bottom)
        elif tab == "community":
            self.draw_community(p, top, bottom)
        elif tab == "messages":
            self.draw_messages(p, top, bottom)
        elif tab == "ranking":
            self.draw_ranking(p, top, bottom)

    # ---- Community leaderboard -------------------------------------------------------------

    def draw_ranking(self, p, top, bottom) -> None:
        ph = p.h
        x, w = p.x + 40, p.w - 80
        scr = self.app.screen
        data = self.ranking
        if data is None:
            self.text("Loading...", ph * 0.03, MUTED, center=(p.centerx, (top + bottom) // 2))
            return
        parts = data.get("parts", [])
        self.text("Score out of 100:  " + "  ·  ".join(f"{pt['label']} {pt['most']}" for pt in parts) +
                  "  (built-in speedruns only)", ph * 0.022, MUTED, topleft=(x, top))
        y = top + ph * 0.04
        players = data.get("players", [])
        if not players:
            self.text("Nobody has a score yet. Play speedruns, set records and collect skins!", ph * 0.028, MUTED,
                      center=(p.centerx, (top + bottom) // 2))
            return
        # columns: place, player, score bar, then each part's raw number
        cols = [("#", 0.0), ("Player", 0.06), ("Score", 0.36), ("WRs", 0.62), ("PRs", 0.71),
                ("Points earned", 0.79), ("Skins", 0.93)]
        for label, fx in cols:
            self.text(label, ph * 0.024, MUTED, topleft=(x + w * fx, y))
        y += ph * 0.038
        row = max(38, int(ph * 0.06))
        me_name = self.on.user.lower() if self.on.logged_in else ""
        mine = data.get("me")
        room = max(1, int((bottom - y - ph * 0.04) // (row + 4)))
        self.scroll = min(self.scroll, max(0, len(players) - room))
        rows = players[self.scroll:self.scroll + room]
        if mine and not any(r["name"].lower() == me_name for r in rows):
            rows = rows[:max(0, room - 1)] + [None, mine]  # you're further down: show your row at the end
        medals = {1: (255, 196, 0), 2: (180, 188, 198), 3: (205, 127, 50)}
        colors = {"wrs": (255, 176, 0), "prs": (61, 111, 232), "earned": (40, 160, 70), "skins": (163, 64, 214)}
        for entry in rows:
            if entry is None:
                self.text("...", row * 0.4, MUTED, midleft=(x + 8, y + row * 0.25))
                y += row * 0.5
                continue
            r = pygame.Rect(x, y, w, row)
            you = entry["name"].lower() == me_name
            pygame.draw.rect(scr, (226, 238, 255) if you else CARD, r, border_radius=8)
            place = entry["place"]
            if place in medals:
                pygame.draw.circle(scr, medals[place], (x + w * 0.02, r.centery), row * 0.3)
            self.text(str(place), row * 0.38, WHITE if place in medals else INK, center=(x + w * 0.02, r.centery))
            rad = row * 0.34
            self.avatar((x + w * 0.06 + rad, r.centery), rad, entry.get("avatar"), entry["name"])
            self.text(entry["name"] + ("  (you)" if you else ""), row * 0.38, INK,
                      midleft=(x + w * 0.06 + 2 * rad + 10, r.centery))
            # the score: a bar split into its parts, and the number
            bar = pygame.Rect(x + w * 0.36, r.centery - row * 0.14, w * 0.17, row * 0.28)
            pygame.draw.rect(scr, (228, 231, 224), bar, border_radius=bar.h // 2)
            bx = bar.x
            for pt in parts:
                seg = bar.w * entry["parts"].get(pt["key"], 0) / 100
                if seg >= 1:
                    pygame.draw.rect(scr, colors.get(pt["key"], ACCENT), (bx, bar.y, seg, bar.h))
                    bx += seg
            self.text(f"{entry['score']:.1f}", row * 0.42, INK, midleft=(bar.right + 10, r.centery))
            for key, fx in (("wrs", 0.62), ("prs", 0.71), ("earned", 0.79), ("skins", 0.93)):
                value = cos.format_points(entry[key]) if key == "earned" else str(entry[key])
                self.text(value, row * 0.36, INK, midleft=(x + w * fx, r.centery))
            y += row + 4
        legend_y = bottom - ph * 0.005
        lx = x
        for pt in parts:
            pygame.draw.circle(scr, colors.get(pt["key"], ACCENT), (lx + 6, legend_y - 6), 6)
            t = self.text(pt["label"], ph * 0.022, MUTED, bottomleft=(lx + 16, legend_y))
            lx = t.right + 22
        if data.get("total", 0) > len(players):
            self.text(f"Top {len(players)} of {data['total']}", ph * 0.022, MUTED, bottomright=(x + w, legend_y))

    # ---- Messages --------------------------------------------------------------------------------

    def wrap(self, text: str, font, width: int) -> list[str]:
        lines, line = [], ""
        for word in text.split(" "):
            while font.size(word)[0] > width:  # a very long word: break it
                cut = len(word)
                while cut > 1 and font.size(word[:cut])[0] > width:
                    cut -= 1
                if line:
                    lines.append(line)
                    line = ""
                lines.append(word[:cut])
                word = word[cut:]
            trial = f"{line} {word}" if line else word
            if font.size(trial)[0] <= width:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
        return lines

    def draw_messages(self, p, top, bottom) -> None:
        ph = p.h
        x, w = p.x + 40, p.w - 80
        scr = self.app.screen
        row = max(48, int(ph * 0.075))
        lw = int(w * 0.33)
        # left: conversations, then friends you haven't messaged yet
        self.text("Chats", ph * 0.03, INK, topleft=(x, top))
        y = top + ph * 0.042
        by_name = {c["name"].lower(): c for c in self.chats}
        people = list(self.chats) + [f for f in self.friends["friends"] if f["name"].lower() not in by_name]
        if not people:
            self.text("Add friends to message them.", ph * 0.024, MUTED, topleft=(x, y))
        fits = max(1, int((bottom - y) // (row + 6)))
        for person in people[:fits]:
            r = pygame.Rect(x, y, lw, row)
            on = (self.chat_with or "").lower() == person["name"].lower()
            pygame.draw.rect(scr, (226, 238, 255) if on else CARD, r, border_radius=8)
            rad = row * 0.34
            self.avatar((r.x + 8 + rad, r.centery), rad, person.get("avatar"), person["name"])
            nx = r.x + 16 + 2 * rad
            self.dot((nx + 4, r.y + row * 0.32), person.get("online"))
            self.text(person["name"], row * 0.34, INK, midleft=(nx + 14, r.y + row * 0.32))
            last = person.get("last")
            if last:
                prev = ("You: " if last["from"].lower() == self.on.user.lower() else "") + last["body"]
                font = self.app.renderer.font(max(10, int(row * 0.28)), False)
                while len(prev) > 3 and font.size(prev)[0] > r.right - nx - 40:
                    prev = prev[:-4] + "..."
                self.text(prev, row * 0.28, MUTED, midleft=(nx + 2, r.y + row * 0.72))
            if person.get("unread"):
                c = (r.right - row * 0.32, r.centery)
                pygame.draw.circle(scr, BAD, c, row * 0.22)
                self.text(str(person["unread"]), row * 0.26, WHITE, center=c)
            self.on.hits.append((r, lambda n=person["name"]: self.open_chat(n)))
            y += row + 6

        # right: the open chat
        cx = x + lw + 20
        cw = x + w - cx
        if not self.chat_with:
            self.text("Pick a friend to chat with.", ph * 0.028, MUTED, center=(cx + cw // 2, (top + bottom) // 2))
            return
        friend = next((f for f in people if f["name"].lower() == self.chat_with.lower()), {"name": self.chat_with})
        head = self.text(friend["name"], ph * 0.034, INK, topleft=(cx, top))
        self.text("online" if friend.get("online") else "offline", ph * 0.022, GOOD if friend.get("online") else MUTED,
                  midleft=(head.right + 12, head.centery))
        area = pygame.Rect(cx, top + ph * 0.05, cw, bottom - top - ph * 0.05 - row - 10)
        pygame.draw.rect(scr, (248, 249, 246), area, border_radius=10)
        font = self.app.renderer.font(max(12, int(ph * 0.026)), False)
        lh = font.get_linesize()
        pad = 10
        # lay the bubbles out from the newest up
        bubbles, total = [], 0
        for m in reversed(self.chat):
            mine = m["from"].lower() == self.on.user.lower()
            lines = self.wrap(m["body"], font, int(cw * 0.68))
            h = len(lines) * lh + 2 * pad
            bubbles.append((m, mine, lines, h))
            total += h + 8
        self.chat_scroll = min(self.chat_scroll, max(0, total - area.h + 10))
        old_clip = scr.get_clip()
        scr.set_clip(area)
        yb = area.bottom - 8 + self.chat_scroll
        for m, mine, lines, h in bubbles:
            yb -= h
            if yb + h < area.y:
                break
            bw = max(font.size(line)[0] for line in lines) + 2 * pad
            br = pygame.Rect(area.right - bw - 10 if mine else area.x + 10, yb, bw, h)
            pygame.draw.rect(scr, ACCENT if mine else (230, 233, 226), br, border_radius=12)
            for i, line in enumerate(lines):
                img = font.render(line, True, WHITE if mine else INK)
                scr.blit(img, (br.x + pad, br.y + pad + i * lh))
            yb -= 8
        scr.set_clip(old_clip)
        if not self.chat and not self.chat_loading:
            self.text(f"Say hi to {self.chat_with}!", ph * 0.026, MUTED, center=area.center)
        if self.chat_more and self.chat_scroll >= total - area.h and not self.chat_loading and self.chat:
            self.load_messages(before=self.chat[0]["id"])  # scrolled to the top: fetch older ones
        iy = area.bottom + 10
        self.on._field("dm", pygame.Rect(cx, iy, int(cw * 0.8), row))
        self.button(pygame.Rect(cx + int(cw * 0.82), iy, int(cw * 0.18), row), "Send", self.send_dm, True)

    # ---- Profile ---------------------------------------------------------------------------------

    def draw_profile(self, p, top, bottom) -> None:
        ph = p.h
        x, w = p.x + 40, p.w - 80
        prof = self.viewing or self.on.me
        if not prof:
            self.text("Loading...", ph * 0.03, MUTED, center=(p.centerx, (top + bottom) // 2))
            return
        mine = self.viewing is None or prof.get("name", "").lower() == self.on.user.lower()
        r = int(ph * 0.075)
        self.avatar((x + r, top + r + 6), r, prof.get("avatar"), prof.get("name", ""))
        tx = x + 2 * r + 24
        name = self.text(prof.get("name", ""), ph * 0.05, INK, topleft=(tx, top + 2))
        rp = prof.get("rp", 0)
        pill = self.rank_pill(prof.get("rank", "Hatchling"), ph * 0.026, topleft=(name.right + 14, name.y + 6))
        nxt = cos.next_rank(rp)
        line = f"{rp} RP" + (f"   ·   {nxt[1] - rp} RP to {nxt[0]}" if nxt else "   ·   top rank!")
        self.text(line, ph * 0.024, MUTED, midleft=(pill.right + 12, pill.centery))
        # rank progress
        lo = cos.RANKS[cos.rank_for(rp)[0]][0]
        frac = 1.0 if not nxt else (rp - lo) / max(1, nxt[1] - lo)
        bar = pygame.Rect(tx, name.bottom + 8, min(w - (tx - x), int(w * 0.6)), 8)
        pygame.draw.rect(self.app.screen, (230, 233, 226), bar, border_radius=4)
        pygame.draw.rect(self.app.screen, cos.rank_for(rp)[2], (bar.x, bar.y, max(8, int(bar.w * frac)), bar.h),
                         border_radius=4)
        stats = (f"Wins {prof.get('wins', 0)}   Losses {prof.get('losses', 0)}   Draws {prof.get('draws', 0)}"
                 f"   ·   World records held: {prof.get('wrs', 0)}   ·   Joined {prof.get('joined', '')}")
        self.text(stats, ph * 0.024, MUTED, topleft=(tx, bar.bottom + 10))
        if "online" in prof and not mine:
            self.dot((tx + 6, bar.bottom + 18 + ph * 0.03), prof.get("online"))
            self.text("Online" + (" (in a match)" if prof.get("in_match") else "") if prof.get("online") else "Offline",
                      ph * 0.024, MUTED, midleft=(tx + 18, bar.bottom + 18 + ph * 0.03))
        y = top + 2 * r + 30
        row = max(32, int(ph * 0.052))

        if not mine:
            self.text("Bio", ph * 0.03, INK, topleft=(x, y))
            self.text(prof.get("bio") or "No bio yet.", ph * 0.026, INK if prof.get("bio") else MUTED,
                      topleft=(x, y + ph * 0.04))
            y += ph * 0.1
            skin = cos.SKIN_BY_ID.get(prof.get("skin") or "")
            self.text("Skin: " + (skin.name if skin else "default"), ph * 0.026, MUTED, topleft=(x, y))
            if skin:
                self.skin_preview(pygame.Rect(x + w * 0.3, y - row * 0.2, int(w * 0.25), row), skin,
                                  pygame.time.get_ticks())
            y += row + 10
            state = prof.get("friend", "none")
            bw = int(w * 0.24)
            name = prof["name"]
            if state == "friends":
                self.button(pygame.Rect(x, y, bw, row), "Play together", lambda: self.play_with(name), True)
                self.button(pygame.Rect(x + bw + 12, y, bw, row), "Message", lambda: self.message(name))
                self.button(pygame.Rect(x + 2 * (bw + 12), y, bw, row), "Remove friend",
                            lambda: self.friend(name, False))
            elif state == "incoming":
                self.button(pygame.Rect(x, y, bw, row), "Accept request", lambda: self.friend(name, True), True)
                self.button(pygame.Rect(x + bw + 12, y, bw, row), "Decline", lambda: self.friend(name, False))
            elif state == "outgoing":
                self.button(pygame.Rect(x, y, bw, row), "Request sent", lambda: None, False, False)
                self.button(pygame.Rect(x + bw + 12, y, bw, row), "Cancel request", lambda: self.friend(name, False))
            else:
                self.button(pygame.Rect(x, y, bw, row), "Add friend", lambda: self.friend(name, True), True)
            self.button(pygame.Rect(x + w - bw, y, bw, row), "Back", self.close_view)
            return

        self.points_badge(prof.get("points", 0), ph * 0.03, topright=(x + w, top + 4))
        # bio
        self.text("Bio", ph * 0.03, INK, topleft=(x, y))
        y += ph * 0.042
        self.on._field("bio", pygame.Rect(x, y, int(w * 0.8), row))
        self.button(pygame.Rect(x + int(w * 0.82), y, int(w * 0.18), row), "Save",
                    lambda: self.save_profile(bio=self.on.fields["bio"].value), True)
        y += row + ph * 0.03
        # picture
        icon, ci = cos.parse_avatar(prof.get("avatar"))
        own = cos.custom_picture(prof.get("avatar"))
        head = self.text("Profile picture", ph * 0.03, INK, topleft=(x, y))
        ub = pygame.Rect(head.right + 20, head.centery - row * 0.42, int(w * 0.22), int(row * 0.84))
        self.button(ub, "Upload picture...", self.choose_picture, True, self.picker is None)
        note = "Using your own picture. Pick an icon below to switch back." if own else \
            "Any image: it's cropped to a square. Or pick an icon and a colour:"
        self.text(note, ph * 0.022, MUTED, midleft=(ub.right + 14, ub.centery))
        if self.typing_path:
            y += ph * 0.05
            self.on._field("picture_path", pygame.Rect(x, y, int(w * 0.8), row))
            self.button(pygame.Rect(x + int(w * 0.82), y, int(w * 0.18), row), "Use", self.picture_from_path, True)
            y += row - ph * 0.005
        y += ph * 0.045
        n = len(cos.AVATAR_ICONS)
        cell = min(int(ph * 0.06), (w - 6 * (n - 1)) // n)
        for i, name_ in enumerate(cos.AVATAR_ICONS):
            c = (x + cell // 2 + i * (cell + 6), y + cell // 2)
            self.avatar(c, cell // 2, f"{name_}:{ci}")
            if name_ == icon and not own:
                pygame.draw.circle(self.app.screen, (255, 170, 0), c, cell // 2 + 3, 3)
            self.on.hits.append((pygame.Rect(c[0] - cell // 2, c[1] - cell // 2, cell, cell),
                                 lambda v=f"{name_}:{ci}": self.save_profile(avatar=v)))
        y += cell + 10
        for i, col in enumerate(cos.AVATAR_COLORS):
            c = (x + cell // 2 + i * (cell + 6), y + cell // 3)
            pygame.draw.circle(self.app.screen, col, c, cell // 3)
            if i == ci and not own:
                pygame.draw.circle(self.app.screen, (255, 170, 0), c, cell // 3 + 3, 3)
            self.on.hits.append((pygame.Rect(c[0] - cell // 3, c[1] - cell // 3, 2 * cell // 3, 2 * cell // 3),
                                 lambda v=f"{icon}:{i}": self.save_profile(avatar=v)))
        y += cell + 4
        skin = cos.SKIN_BY_ID.get(prof.get("skin") or "")
        self.text("Skin: " + (skin.name if skin else "default (the menu's Snake colour)") +
                  "   ·   change it in Store > Collection", ph * 0.024, MUTED, topleft=(x, y))

    def close_view(self) -> None:
        self.viewing = None
        self.on.fields["bio"].value = (self.on.me or {}).get("bio", "")

    # ---- Friends ---------------------------------------------------------------------------------

    def person_row(self, rect, person: dict, buttons, clickable: bool = True) -> None:
        scr = self.app.screen
        pygame.draw.rect(scr, CARD, rect, border_radius=8)
        r = rect.h * 0.36
        self.avatar((rect.x + 8 + r, rect.centery), r, person.get("avatar"), person["name"])
        nx = rect.x + 16 + 2 * r
        self.dot((nx + 4, rect.centery), person.get("online"))
        name = self.text(person["name"], rect.h * 0.42, INK, midleft=(nx + 14, rect.centery))
        self.rank_pill(person.get("rank", ""), rect.h * 0.3, midleft=(name.right + 10, rect.centery - rect.h * 0.12))
        if person.get("in_match"):
            self.text("in a match", rect.h * 0.28, MUTED, midleft=(name.right + 10 + rect.h * 1.9, rect.centery))
        bx = rect.right - 6
        for label, action, primary in reversed(buttons):
            bw = max(60, int(rect.h * 0.3 * len(label) + 20))
            b = pygame.Rect(bx - bw, rect.y + 5, bw, rect.h - 10)
            self.button(b, label, action, primary)
            bx -= bw + 6
        if clickable:
            self.on.hits.append((pygame.Rect(rect.x, rect.y, max(1, bx - rect.x), rect.h),
                                 lambda n=person["name"]: self.view_profile(n)))

    def draw_friends(self, p, top, bottom) -> None:
        ph = p.h
        x, w = p.x + 40, p.w - 80
        row = max(32, int(ph * 0.05))
        col = (w - 20) // 2
        # left: find players
        self.text("Find players", ph * 0.03, INK, topleft=(x, top))
        y = top + ph * 0.04
        self.on._field("users", pygame.Rect(x, y, col, row))
        y += row + 8
        fr = self.friends
        known = {f["name"]: "friends" for f in fr["friends"]}
        known.update({f["name"]: "incoming" for f in fr["incoming"]})
        known.update({f["name"]: "outgoing" for f in fr["outgoing"]})
        if self.users_query and not self.users:
            self.text("No players found.", ph * 0.024, MUTED, topleft=(x, y))
        for u in self.users[:max(1, int((bottom - y) // (row + 6)))]:
            name = u["name"]
            if name.lower() == self.on.user.lower():
                btns = [("You", lambda: None, False)]
            elif known.get(name) == "friends":
                btns = [("Friends", lambda: None, False)]
            elif known.get(name) == "outgoing":
                btns = [("Requested", lambda: None, False)]
            elif known.get(name) == "incoming":
                btns = [("Accept", lambda n=name: self.friend(n, True), True)]
            else:
                btns = [("Add", lambda n=name: self.friend(n, True), True)]
            self.person_row(pygame.Rect(x, y, col, row), u, btns)
            y += row + 6

        # right: requests and friends
        rx = x + col + 20
        y = top
        if fr["incoming"] or fr["outgoing"]:
            self.text("Friend requests", ph * 0.03, INK, topleft=(rx, y))
            y += ph * 0.04
            for f in fr["incoming"][:3]:
                self.person_row(pygame.Rect(rx, y, col, row), f,
                                [("Accept", lambda n=f["name"]: self.friend(n, True), True),
                                 ("No", lambda n=f["name"]: self.friend(n, False), False)])
                y += row + 6
            for f in fr["outgoing"][:2]:
                self.person_row(pygame.Rect(rx, y, col, row), f,
                                [("Cancel", lambda n=f["name"]: self.friend(n, False), False)])
                y += row + 6
            y += 8
        online = sum(1 for f in fr["friends"] if f["online"])
        self.text(f"Friends ({len(fr['friends'])}, {online} online)", ph * 0.03, INK, topleft=(rx, y))
        y += ph * 0.04
        if not fr["friends"]:
            self.text("Search for players on the left and add them." if self.friends_loaded else "Loading...",
                      ph * 0.024, MUTED, topleft=(rx, y))
        fits = max(1, int((bottom - y) // (row + 6)))
        self.scroll = min(self.scroll, max(0, len(fr["friends"]) - fits))
        for f in fr["friends"][self.scroll:self.scroll + fits]:
            btns = [("Message", lambda n=f["name"]: self.message(n), False)]
            if f["online"]:
                btns.append(("Play", lambda n=f["name"]: self.play_with(n), True))
            self.person_row(pygame.Rect(rx, y, col, row), f, btns)
            y += row + 6

    # ---- Store ---------------------------------------------------------------------------------

    def draw_store(self, p, top, bottom) -> None:
        ph = p.h
        x, w = p.x + 40, p.w - 80
        me = self.on.me or {}
        owned = set(me.get("inventory") or [])
        points = me.get("points", 0)
        now = pygame.time.get_ticks()
        row = max(30, int(ph * 0.045))
        for i, (tab, label) in enumerate(STORE_TABS):
            r = pygame.Rect(x + i * (int(w * 0.17) + 8), top, int(w * 0.17), row)
            on = self.store_tab == tab
            pygame.draw.rect(self.app.screen, INK if on else (236, 239, 232), r, border_radius=r.h // 2)
            self.text(label, row * 0.48, WHITE if on else INK, center=r.center)
            if not self.opening:
                self.on.hits.append((r, lambda t=tab: self.set_store_tab(t)))
        self.points_badge(points, ph * 0.032, midright=(x + w, top + row // 2))
        y = top + row + 12
        if self.opening:
            self.draw_opening(pygame.Rect(x, y, w, bottom - y), now)
        elif self.store_tab == "shop":
            items = [f"skin:{s.id}" for s in cos.SKINS if s.shop]
            self.text("Common, Uncommon and Rare skins. Epic, Legendary and Mythic ones only come from loot boxes.",
                      ph * 0.022, MUTED, topleft=(x, y))
            y += ph * 0.035
            self.item_grid(pygame.Rect(x, y, w, bottom - y), items, now, owned, points, shop=True)
        elif self.store_tab == "collection":
            mine = [it for it in cos.ALL_ITEMS if it in owned]
            equipped = me.get("skin") or ""
            b = pygame.Rect(x, y, int(w * 0.32), row)
            self.button(b, "Default skin" + ("  (equipped)" if not equipped else ""), lambda: self.equip(""),
                        not equipped, bool(equipped))
            self.text(f"You own {len(mine)} of {len(cos.ALL_ITEMS)} items.", ph * 0.024, MUTED,
                      midleft=(b.right + 16, b.centery))
            y += row + 10
            if not mine:
                self.text("Nothing yet: buy skins in the Shop or open loot boxes.", ph * 0.026, MUTED, topleft=(x, y))
            self.item_grid(pygame.Rect(x, y, w, bottom - y), mine, now, owned, points, shop=False)
        else:
            self.draw_crates(pygame.Rect(x, y, w, bottom - y), points, now)

    def set_store_tab(self, tab: str) -> None:
        self.store_tab = tab
        self.scroll = 0

    def item_grid(self, area, items, now, owned, points, shop) -> None:
        cols = 6
        gap = 10
        cw = (area.w - gap * (cols - 1)) // cols
        ch = int(cw * 0.95)
        rows_fit = max(1, (area.h + gap) // (ch + gap))
        total_rows = math.ceil(len(items) / cols)
        self.scroll = min(self.scroll, max(0, total_rows - rows_fit))
        me = self.on.me or {}
        equipped = me.get("skin") or ""
        packs_on = self.app.settings["packs"]
        for k, item in enumerate(items[self.scroll * cols:(self.scroll + rows_fit) * cols]):
            r = pygame.Rect(area.x + (k % cols) * (cw + gap), area.y + (k // cols) * (ch + gap), cw, ch)
            self.card(pygame.Rect(r.x, r.y, r.w, int(r.h * 0.74)), item, now)
            b = pygame.Rect(r.x + 4, r.y + int(r.h * 0.77), r.w - 8, int(r.h * 0.22))
            kind, _, key = item.partition(":")
            if shop:
                price = cos.SKIN_BY_ID[key].price
                if item in owned:
                    self.button(b, "Owned", lambda: None, False, False)
                else:
                    self.button(b, cos.format_points(price), lambda it=item: self.buy(it), True, points >= price)
            elif kind == "skin":
                on = equipped == key
                self.button(b, "Equipped" if on else "Equip", lambda s=key: self.equip(s), not on, not on)
            else:
                on = f"builtin:{key}" in packs_on
                self.button(b, "Turn off" if on else "Use pack", lambda pk=key: self.use_pack(pk), not on)
        if total_rows > rows_fit:
            self.text(f"Scroll for more ({self.scroll + 1}-{min(total_rows, self.scroll + rows_fit)} of "
                      f"{total_rows} rows)", 16, MUTED, bottomright=(area.right, area.bottom + 18))

    def draw_crates(self, area, points, now) -> None:
        scr = self.app.screen
        n = len(cos.CRATES)
        gap = 14
        cw = (area.w - gap * (n - 1)) // n
        ch = min(area.h - 10, int(cw * 1.6))
        for i, crate in enumerate(cos.CRATES):
            r = pygame.Rect(area.x + i * (cw + gap), area.y, cw, ch)
            pygame.draw.rect(scr, CARD, r, border_radius=12)
            pygame.draw.rect(scr, crate.color, r, 3, border_radius=12)
            # the box itself
            bw, bh = int(cw * 0.5), int(cw * 0.36)
            bob = math.sin(now / 400 + i) * 3
            box = pygame.Rect(0, 0, bw, bh)
            box.midtop = (r.centerx, r.y + 14 + bob + bh * 0.25)
            dark = tuple(int(c * 0.7) for c in crate.color)
            pygame.draw.rect(scr, crate.color, box, border_radius=6)
            lid = pygame.Rect(box.x - 4, box.y - bh * 0.28, bw + 8, bh * 0.32)
            pygame.draw.rect(scr, dark, lid, border_radius=5)
            pygame.draw.rect(scr, dark, (box.centerx - bw * 0.07, lid.y, bw * 0.14, box.bottom - lid.y))
            pygame.draw.circle(scr, (255, 240, 180), (box.centerx, lid.bottom), bw * 0.07)
            y = box.bottom + 10
            self.text(crate.name, ch * 0.075, INK, midtop=(r.centerx, y))
            y += ch * 0.09
            for rarity in cos.RARITIES:
                pct = crate.odds.get(rarity)
                if pct:
                    self.text(f"{cos.RARITY_NAMES[rarity]}  {pct:g}%", ch * 0.052, cos.RARITY_COLORS[rarity],
                              midtop=(r.centerx, y))
                    y += ch * 0.06
            b = pygame.Rect(r.x + 10, r.bottom - int(ch * 0.13) - 8, r.w - 20, int(ch * 0.13))
            self.button(b, f"Open  {cos.format_points(crate.price)}", lambda c=crate: self.open_crate(c), True,
                        points >= crate.price and not self.busy)
        self.text("Loot boxes hold skins and texture packs. Duplicates turn back into snake points.",
                  area.h * 0.035 + 6, MUTED, midtop=(area.centerx, area.y + ch + 10))

    def draw_opening(self, area, now) -> None:
        """The spinning reel: cards race past a marker and slow down onto your prize."""
        o = self.opening
        scr = self.app.screen
        crate = o["crate"]
        t = min(1.0, (now - o["start"]) / REEL_MS)
        cw = max(90, area.w // 6)
        ch = int(cw * 1.15)
        gap = 8
        step = cw + gap
        reel_y = area.y + (area.h - ch) // 2 - 20
        target = REEL_WIN * step + cw / 2 + o["land"] * cw  # reel position under the marker at the end
        pos = target * ease_out(t)
        clip = pygame.Rect(area.x, reel_y - 12, area.w, ch + 24)
        pygame.draw.rect(scr, (34, 40, 30), clip, border_radius=12)
        old = scr.get_clip()
        scr.set_clip(clip)
        first = max(0, int((pos - area.w / 2) // step) - 1)
        for k in range(first, min(REEL_CARDS, first + area.w // step + 3)):
            cx = area.centerx + k * step - pos
            self.card(pygame.Rect(int(cx), reel_y, cw, ch), o["reel"][k], now)
        scr.set_clip(old)
        # the marker
        pygame.draw.line(scr, (255, 200, 0), (area.centerx, clip.y - 6), (area.centerx, clip.bottom + 6), 4)
        for y, d in ((clip.y - 6, 1), (clip.bottom + 6, -1)):
            pygame.draw.polygon(scr, (255, 200, 0), [(area.centerx - 9, y), (area.centerx + 9, y),
                                                     (area.centerx, y + 12 * d)])
        # a tick for every card that passes, like the real thing
        card_now = int(pos // step)
        if card_now != o["last_card"] and not o["done"]:
            o["last_card"] = card_now
            self.app.sfx.play("turn")
        self.text(f"Opening a {crate.name}...", area.h * 0.06, INK, midbottom=(area.centerx, clip.y - 14))
        if t >= 1.0:
            res = o["result"]
            rarity = cos.item_rarity(res["item"])
            color = cos.RARITY_COLORS[rarity]
            text_color = (110, 118, 122) if rarity == "common" else color  # (the light grey is hard to read)
            if not o["done"]:
                o["done"] = True
                self.app.sfx.play("win")
                o["done_at"] = now
            glow = 0.5 + 0.5 * math.sin((now - o["done_at"]) / 160)
            hl = pygame.Rect(0, 0, cw + 16, ch + 16)
            hl.center = (area.centerx + int(REEL_WIN * step - pos + cw / 2), reel_y + ch // 2)
            pygame.draw.rect(scr, color, hl, max(3, int(4 + 4 * glow)), border_radius=14)
            y = clip.bottom + 16
            self.text(f"{cos.RARITY_NAMES[rarity]}!  {cos.item_name(res['item'])}", area.h * 0.075, text_color,
                      midtop=(area.centerx, y))
            y += area.h * 0.09
            note = "New! It's in your Collection." if res.get("new") else \
                f"You already had it: +{cos.format_points(res.get('refund', 0))} snake points back."
            self.text(note, area.h * 0.045, INK, midtop=(area.centerx, y))
            b = pygame.Rect(0, 0, int(area.w * 0.25), max(34, int(area.h * 0.09)))
            b.midtop = (area.centerx, y + area.h * 0.07)
            self.button(b, "Continue", self.finish_opening, True)

    # ---- Community ---------------------------------------------------------------------------------

    def draw_community(self, p, top, bottom) -> None:
        ph = p.h
        x, w = p.x + 40, p.w - 80
        row = max(32, int(ph * 0.05))
        self.on._field("community", pygame.Rect(x, top, int(w * 0.6), row))
        self.button(pygame.Rect(x + int(w * 0.62), top, int(w * 0.38), row),
                    f"Share my categories ({len(self.app.custom_cats)})", self.share_categories, False,
                    self.on.logged_in and bool(self.app.custom_cats))
        y = top + row + 8
        self.text("Custom speedrun categories players have made. Records count, but they don't earn snake points.",
                  ph * 0.022, MUTED, topleft=(x, y))
        y += ph * 0.035
        if self.community is None:
            self.text("Loading...", ph * 0.026, MUTED, topleft=(x, y))
            return
        if not self.community:
            self.text("Nothing found." if self.community_query else
                      "No community categories yet. Make one with the Speedrun checkbox in the menu and share it!",
                      ph * 0.026, MUTED, topleft=(x, y))
            return
        rh = max(64, int(row * 2.0))
        fits = max(1, int((bottom - y) // (rh + 8)))
        self.scroll = min(self.scroll, max(0, len(self.community) - fits))
        saved = {c.id for c in self.app.custom_cats}
        for c in self.community[self.scroll:self.scroll + fits]:
            r = pygame.Rect(x, y, w, rh)
            pygame.draw.rect(self.app.screen, CARD, r, border_radius=8)
            bw = int(w * 0.11)
            mine = self.on.logged_in and c["creator"].lower() == self.on.user.lower()
            if c["id"] == self.renaming:
                fr = pygame.Rect(r.x + 8, r.y + 8, int(w * 0.4), int(rh * 0.44))
                self.on._field("rename", fr)
                self.button(pygame.Rect(fr.right + 8, fr.y, int(w * 0.1), fr.h), "Save", self.save_rename, True)
                self.button(pygame.Rect(fr.right + 16 + int(w * 0.1), fr.y, int(w * 0.1), fr.h), "Cancel",
                            self.cancel_rename)
            else:
                name = self.text(c["name"], rh * 0.32, INK, topleft=(r.x + 14, r.y + rh * 0.12))
                by = self.text(f"by {c['creator']}" + ("  (you)" if mine else ""), rh * 0.24, ACCENT,
                               midleft=(name.right + 12, name.centery))
                if mine:
                    self.button(pygame.Rect(by.right + 14, name.centery - rh * 0.23, int(w * 0.12), int(rh * 0.46)),
                                "Rename", lambda e=c: self.start_rename(e))
            try:
                rules = describe({**c["def"], "goal": c["def"].get("goal")})
            except (KeyError, TypeError, ValueError):
                rules = ""
            wr = c.get("wr")
            sub = rules + (f"   WR {format_time(wr['time_ms'])} by {wr['player']}" if wr else "   No runs yet") + \
                f"   ·   {c['players']} player{'s' if c['players'] != 1 else ''}"
            self.text(sub, rh * 0.22, MUTED, bottomleft=(r.x + 14, r.bottom - rh * 0.14))
            self.button(pygame.Rect(r.right - bw - 10, r.y + rh * 0.2, bw, rh * 0.6), "Play",
                        lambda e=c: self.save_category(e, True), True, not self.on.mods_on)
            done = c["id"] in saved
            self.button(pygame.Rect(r.right - 2 * bw - 20, r.y + rh * 0.2, bw, rh * 0.6), "Saved" if done else "Save",
                        lambda e=c: self.save_category(e, False), False, not done)
            y += rh + 8
        if len(self.community) > fits:
            self.text(f"{self.scroll + 1}-{self.scroll + fits} of {len(self.community)} (scroll for more)",
                      ph * 0.022, MUTED, topleft=(x, y))
