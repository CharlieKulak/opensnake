"""Talking to an OpenSnake server, from the desktop game or the browser.

Both kinds of request are non-blocking: start one, then check on it each
frame. On the desktop they run on background threads (urllib and the
``websockets`` library); in the browser they use the page's own fetch() and
WebSocket through pygbag's link to JavaScript.
"""

from __future__ import annotations

import importlib
import json
import queue
import sys
import threading
import urllib.error
import urllib.request

WEB = sys.platform == "emscripten"

# Small JavaScript helper installed once into the page (browser build only).
_JS_BRIDGE = r"""
window.osnet = window.osnet || {
  sockets: {}, results: {},
  http(id, method, url, body, token) {
    const h = {'Content-Type': 'application/json'};
    if (token) h['Authorization'] = 'Bearer ' + token;
    fetch(url, {method: method, headers: h, body: body || undefined})
      .then(async r => { osnet.results[id] = JSON.stringify({status: r.status, body: await r.text()}); })
      .catch(e => { osnet.results[id] = JSON.stringify({status: 0, body: '', error: String(e)}); });
  },
  take(id) { const r = osnet.results[id]; if (r === undefined) return ''; delete osnet.results[id]; return r; },
  open(id, url) {
    const s = {ws: new WebSocket(url), inbox: [], state: 'connecting'};
    osnet.sockets[id] = s;
    s.ws.onopen = () => s.state = 'open';
    s.ws.onclose = () => { if (s.state !== 'error') s.state = 'closed'; };
    s.ws.onerror = () => s.state = 'error';
    s.ws.onmessage = e => s.inbox.push(e.data);
  },
  send(id, text) { const s = osnet.sockets[id]; if (s && s.state === 'open') s.ws.send(text); },
  drain(id) { const s = osnet.sockets[id]; if (!s) return '[]'; const out = JSON.stringify(s.inbox); s.inbox = []; return out; },
  status(id) { const s = osnet.sockets[id]; return s ? s.state : 'closed'; },
  close(id) { const s = osnet.sockets[id]; if (s) { try { s.ws.close(); } catch (e) {} delete osnet.sockets[id]; } },
  get(k) { return localStorage.getItem(k) || ''; },
  set(k, v) { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); },
  // Choose an image file; it comes back as a square PNG (base64) of size x size, cropped to the middle.
  pick(size) {
    osnet.picked = {state: 'picking', data: ''};
    const input = document.createElement('input');
    input.type = 'file'; input.accept = 'image/*'; input.style.display = 'none';
    document.body.appendChild(input);  // (some browsers only open pickers that are on the page)
    const done = () => { if (input.parentNode) input.parentNode.removeChild(input); };
    input.onchange = () => {
      done();
      const file = input.files[0];
      if (!file) { osnet.picked.state = 'cancel'; return; }
      const img = new Image();
      img.onload = () => {
        const c = document.createElement('canvas'); c.width = c.height = size;
        const side = Math.min(img.width, img.height);
        c.getContext('2d').drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, size, size);
        osnet.picked = {state: 'done', data: c.toDataURL('image/png').split(',')[1]};
        URL.revokeObjectURL(img.src);
      };
      img.onerror = () => { osnet.picked.state = 'error'; };
      img.src = URL.createObjectURL(file);
    };
    input.oncancel = () => { done(); osnet.picked.state = 'cancel'; };
    input.click();
  },
  pickState() { return JSON.stringify(osnet.picked || {state: 'idle', data: ''}); }
};
"""

_ids = iter(range(1, 1 << 30))
_bridge_ready = False


def _window():
    import platform as pygbag_platform  # pygbag's module of this name is the page
    return pygbag_platform.window


def _js(expr: str) -> str:
    """Evaluate JavaScript in the page and return the result as a string."""
    global _bridge_ready
    w = _window()
    if not _bridge_ready:  # install the helper once (the JS side ignores repeats too)
        w.eval(_JS_BRIDGE)
        _bridge_ready = True
    w.eval(f"window.osnet_out = String({expr});")
    return str(w.osnet_out)


def _q(value) -> str:
    """A Python value as a JavaScript literal (JSON is valid JS)."""
    return json.dumps(value)


# ---- browser helpers -------------------------------------------------------------------

def page_origin() -> str:
    """The website the browser game was loaded from, e.g. https://snake.example.com."""
    return _js("location.origin") if WEB else ""


def set_page_title(title: str) -> None:
    """Browser tab title (shows the match code while you're in one)."""
    if WEB:
        _js(f"document.title = {_q(title)}")


def web_storage_get(key: str) -> str:
    return _js(f"osnet.get({_q(key)})") if WEB else ""


def web_storage_set(key: str, value: str) -> None:
    if WEB:
        _js(f"osnet.set({_q(key)}, {_q(value)})")


# ---- HTTP -------------------------------------------------------------------------------

class Request:
    """An HTTP request in flight. Check ``done``; then read ``status`` and ``data``."""

    def __init__(self, method: str, url: str, body: dict | None = None, token: str | None = None):
        self.done = False
        self.status = 0
        self.data: dict = {}
        self.error = ""
        payload = json.dumps(body) if body is not None else None
        if WEB:
            self.id = next(_ids)
            _js(f"osnet.http({self.id}, {_q(method)}, {_q(url)}, {_q(payload)}, {_q(token or '')})")
        else:
            threading.Thread(target=self._run, args=(method, url, payload, token), daemon=True).start()

    def _finish(self, status: int, text: str, error: str = "") -> None:
        self.status, self.error = status, error
        try:
            self.data = json.loads(text) if text else {}
        except ValueError:
            self.data = {}
            self.error = self.error or "The server sent something unexpected."
        if not isinstance(self.data, dict):
            self.data = {}
        self.done = True

    def _run(self, method, url, payload, token):
        req = urllib.request.Request(url, data=payload.encode() if payload else None, method=method,
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self._finish(resp.status, resp.read().decode())
        except urllib.error.HTTPError as e:
            self._finish(e.code, e.read().decode(errors="replace"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            self._finish(0, "", f"Can't reach the server ({getattr(e, 'reason', e)}).")

    def poll(self) -> bool:
        """True once finished (call every frame in the browser build)."""
        if not self.done and WEB:
            raw = _js(f"osnet.take({self.id})")
            if raw:
                r = json.loads(raw)
                self._finish(r["status"], r.get("body", ""),
                             "Can't reach the server." if r["status"] == 0 else "")
        return self.done

    @property
    def ok(self) -> bool:
        return self.done and 200 <= self.status < 300

    @property
    def message(self) -> str:
        return self.data.get("error") or self.error or f"Server error ({self.status})."


# ---- WebSocket ----------------------------------------------------------------------------

class Socket:
    """A WebSocket connection. ``state`` is connecting / open / closed / error."""

    def __init__(self, url: str):
        self.url = url
        self.state = "connecting"
        self._inbox: queue.Queue = queue.Queue()
        self._conn = None
        if WEB:
            self.id = next(_ids)
            _js(f"osnet.open({self.id}, {_q(url)})")
        else:
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            client = importlib.import_module("websockets.sync.client")  # desktop only
            self._conn = client.connect(self.url, open_timeout=8)
            self.state = "open"
            for text in self._conn:
                self._inbox.put(text)
            self.state = "closed"
        except Exception:  # connection refused, dropped, bad address...
            self.state = "error" if self.state == "connecting" else "closed"

    def send(self, msg: dict) -> None:
        text = json.dumps(msg, separators=(",", ":"))
        if WEB:
            _js(f"osnet.send({self.id}, {_q(text)})")
        elif self._conn and self.state == "open":
            try:
                self._conn.send(text)
            except Exception:
                self.state = "closed"

    def poll(self) -> list[dict]:
        """Messages received since last time."""
        if WEB:
            self.state = _js(f"osnet.status({self.id})")
            texts = json.loads(_js(f"osnet.drain({self.id})"))
        else:
            texts = []
            while not self._inbox.empty():
                texts.append(self._inbox.get_nowait())
        out = []
        for t in texts:
            try:
                msg = json.loads(t)
            except ValueError:
                continue
            if isinstance(msg, dict):
                out.append(msg)
        return out

    def close(self) -> None:
        if WEB:
            _js(f"osnet.close({self.id})")
        elif self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self.state = "closed"


# ---- profile pictures ---------------------------------------------------------------------

PICTURE_SIZE = 128


def square_png(surface) -> str:
    """The middle square of an image, as a PICTURE_SIZE PNG in base64."""
    import base64
    import io

    import pygame
    w, h = surface.get_size()
    side = min(w, h)
    square = surface.subsurface(((w - side) // 2, (h - side) // 2, side, side))
    small = pygame.transform.smoothscale(square.convert_alpha() if pygame.display.get_surface() else square,
                                         (PICTURE_SIZE, PICTURE_SIZE))
    buf = io.BytesIO()
    pygame.image.save(small, buf, "picture.png")
    return base64.b64encode(buf.getvalue()).decode()


def decode_png(data: bytes):
    """A PNG (bytes) as a pygame image.

    pygbag's pygame.image.load can't read from memory in the browser, so there
    the bytes go through a file in the page's own (in-memory) file system."""
    import io

    import pygame
    if not WEB:
        return pygame.image.load(io.BytesIO(data), "picture.png")
    path = f"/tmp/opensnake-picture-{next(_ids)}.png"
    with open(path, "wb") as f:
        f.write(data)
    try:
        return pygame.image.load(path)
    finally:
        import os
        os.remove(path)


def load_picture(path: str) -> str:
    """An image file as a square PNG (base64); raises ValueError if it can't be read."""
    import pygame
    try:
        return square_png(pygame.image.load(path.strip().strip('"')))
    except (pygame.error, OSError, FileNotFoundError) as e:
        raise ValueError(f"Couldn't open that image: {e}") from None


def _file_dialog() -> str | None:
    """Ask for an image file with the system's dialog: the path, "" if cancelled, None if there's no dialog."""
    import shutil
    import subprocess
    title = "Choose a profile picture"
    commands = []
    if sys.platform == "darwin":
        commands.append(["osascript", "-e", f'POSIX path of (choose file of type {{"public.image"}} '
                                            f'with prompt "{title}")'])
    elif sys.platform.startswith("linux"):
        commands.append(["zenity", "--file-selection", f"--title={title}",
                         "--file-filter=Images | *.png *.jpg *.jpeg *.gif *.bmp *.webp"])
        commands.append(["kdialog", "--title", title, "--getopenfilename", ".", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"])
    for cmd in commands:
        if shutil.which(cmd[0]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except (OSError, subprocess.SubprocessError):
                continue
            return out.stdout.strip() if out.returncode == 0 else ""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title=title, filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("All files", "*.*")])
        root.destroy()
        return path or ""
    except Exception:  # no tkinter (ImportError), or no display for it (TclError)
        return None


class ImagePicker:
    """Choose an image for a profile picture without freezing the game for long.

    ``state``: picking / done / cancel / error / no-dialog (the desktop has no file
    dialog available: type a path instead). ``data`` is the PNG in base64 when done.
    """

    def __init__(self):
        self.state, self.data, self.error = "picking", "", ""
        if WEB:
            _js(f"osnet.pick({PICTURE_SIZE})")
            return
        path = _file_dialog()  # (a short, modal dialog: fine to wait for)
        if path is None:
            self.state = "no-dialog"
            return
        if not path:
            self.state = "cancel"
            return
        try:
            self.data, self.state = load_picture(path), "done"
        except ValueError as e:
            self.state, self.error = "error", str(e)

    def poll(self) -> bool:
        """True once the choice is over (whatever the outcome)."""
        if WEB and self.state == "picking":
            got = json.loads(_js("osnet.pickState()"))
            self.state, self.data = got.get("state", "picking"), got.get("data", "")
            if self.state == "error":
                self.error = "The browser couldn't read that image."
        return self.state != "picking"


def ws_url(base: str, path: str = "/ws") -> str:
    """http(s)://host -> ws(s)://host/ws"""
    base = base.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[8:] + path
    if base.startswith("http://"):
        return "ws://" + base[7:] + path
    return "ws://" + base + path
