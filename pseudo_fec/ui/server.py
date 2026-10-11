"""Serveur web LOCAL (127.0.0.1 uniquement) servant l'interface HTML.

Protections : jeton de session (cookie HttpOnly + en-tête), contrôle des
en-têtes Host/Origin (anti rebond DNS / requêtes inter-sites), aucun CORS,
aucune ressource externe, journal d'accès sans chemin ni nom de fichier.
Le serveur ne fait AUCUN appel sortant.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .. import __version__
from ..config import Config
from ..errors import PseudoFecError
from .api import AppState

STATIC = Path(__file__).parent / "static"
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/app.js": ("app.js", "text/javascript; charset=utf-8"),
         "/style.css": ("style.css", "text/css; charset=utf-8")}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class Handler(BaseHTTPRequestHandler):
    server: "PseudoFecServer"  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # journal volontairement muet
        return

    # ---- helpers
    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        ok_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in ok_hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in ok_hosts}

    def _cookie_token(self) -> str:
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "pf_token":
                return v
        return ""

    def _authed(self, api: bool) -> bool:
        tok = self.server.token
        if not secrets.compare_digest(self._cookie_token(), tok):
            return False
        if api:
            return secrets.compare_digest(self.headers.get("X-PF-Token", ""), tok)
        return True

    def _send(self, code: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                         "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _err(self, code: int, msg: str) -> None:
        self._json(code, {"error": msg})

    # ---- GET
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._err(HTTPStatus.FORBIDDEN, "Hôte non autorisé.")
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/" and q.get("t", [""])[0] and secrets.compare_digest(q["t"][0], self.server.token):
            return self._send(HTTPStatus.FOUND, b"", "text/plain",
                              {"Location": "/", "Set-Cookie": f"pf_token={self.server.token}; HttpOnly; SameSite=Strict; Path=/"})
        if url.path == "/favicon.ico":
            return self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
        if url.path in FILES:
            if not self._authed(api=False):
                return self._err(HTTPStatus.UNAUTHORIZED, "Session non autorisée : relancez l'application.")
            name, ctype = FILES[url.path]
            body = (STATIC / name).read_bytes()
            if name == "index.html":
                body = body.replace(b"__TOKEN__", self.server.token.encode()).replace(b"__VERSION__", __version__.encode())
            return self._send(HTTPStatus.OK, body, ctype)
        if url.path.startswith("/api/"):
            if not self._authed(api=True):
                return self._err(HTTPStatus.UNAUTHORIZED, "Non autorisé.")
            return self._dispatch("GET", url.path, b"")
        self._err(HTTPStatus.NOT_FOUND, "Introuvable.")

    # ---- POST
    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._err(HTTPStatus.FORBIDDEN, "Hôte non autorisé.")
        if not self.path.startswith("/api/") or not self._authed(api=True):
            return self._err(HTTPStatus.UNAUTHORIZED, "Non autorisé.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._err(HTTPStatus.BAD_REQUEST, "Requête invalide.")
        limit = int(self.server.app.cfg.get("max_fec_mb") or 200) * 1024 * 1024 + 4096
        if length < 0 or length > limit:
            self.close_connection = True
            return self._err(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Fichier trop volumineux.")
        body = self.rfile.read(length) if length else b""
        self._dispatch("POST", urllib.parse.urlsplit(self.path).path, body)

    def _dispatch(self, method: str, path: str, body: bytes) -> None:
        self.server.touch()
        try:
            result = self.server.app.handle(method, path, body, self.headers)
        except PseudoFecError as e:
            return self._err(HTTPStatus.BAD_REQUEST, str(e))
        except Exception:  # message générique : une trace pourrait citer des données
            return self._err(HTTPStatus.INTERNAL_SERVER_ERROR, "Erreur interne (aucun détail affiché par confidentialité).")
        if result.get("_quit"):
            self._json(HTTPStatus.OK, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._json(HTTPStatus.OK, result)


class PseudoFecServer(_Server):
    def __init__(self, cfg: Config, port: int = 0, idle_timeout_s: float | None = None):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.app = AppState(cfg)
        self._last = time.monotonic()
        self._idle = idle_timeout_s
        if idle_timeout_s:
            threading.Thread(target=self._watchdog, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/?t={self.token}"

    def touch(self) -> None:
        self._last = time.monotonic()

    def _watchdog(self) -> None:
        while True:
            time.sleep(5)
            if self._idle and time.monotonic() - self._last > self._idle:
                self.shutdown()
                return


def run(cfg: Config | None = None, open_browser: bool = True, port: int = 0) -> None:
    cfg = cfg or Config.load()
    idle = float(cfg.get("idle_timeout_s") or 600)
    srv = PseudoFecServer(cfg, port=port, idle_timeout_s=idle)
    print(f"Pseudo-FEC {__version__} — interface locale : {srv.url}")
    print("Fermez cette fenêtre ou cliquez sur « Quitter » pour arrêter l'application.")
    if open_browser:
        webbrowser.open(srv.url)
    try:
        srv.serve_forever(poll_interval=0.5)
    finally:
        srv.app.close()
        srv.server_close()
