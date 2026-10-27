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
  set(k, v) { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); }
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


def ws_url(base: str, path: str = "/ws") -> str:
    """http(s)://host -> ws(s)://host/ws"""
    base = base.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[8:] + path
    if base.startswith("http://"):
        return "ws://" + base[7:] + path
    return "ws://" + base + path
