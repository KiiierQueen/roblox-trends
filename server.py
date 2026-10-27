"""Локальный веб-сервер: отдаёт дашборд и JSON-API."""
import hashlib
import hmac
import ipaddress
import json
import os
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import analytics
import collector
import config
import db

STATIC = os.path.join(config.ROOT, "static")
PUBLIC_PATHS = ("/login", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png")

LOGIN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вход — Roblox Trend Tracker</title>
<link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#1a1a19">
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0d0d0d;
color:#f0efec;font:16px system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px;box-sizing:border-box}
form{background:#1a1a19;border:1px solid #33332f;border-radius:14px;padding:24px;width:100%;max-width:340px}
h1{font-size:19px;margin:0 0 16px}input,button{width:100%;box-sizing:border-box;font:inherit;padding:11px 12px;
border-radius:10px;border:1px solid #33332f;background:#0d0d0d;color:inherit;margin-bottom:10px}
button{background:#3987e5;border-color:#3987e5;color:#fff;cursor:pointer}.err{color:#ff8f86;font-size:14px;min-height:20px}
</style></head><body><form method="post" action="/login"><h1>Roblox Trend Tracker</h1>
<input type="password" name="password" placeholder="Пароль" autofocus autocomplete="current-password">
<div class="err">%ERR%</div><button>Войти</button></form></body></html>"""


def _token(password):
    return hmac.new(password.encode("utf-8"), b"rtt-session-v1", hashlib.sha256).hexdigest()


def _is_private(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_loopback
    except ValueError:
        return False


def make_handler(cfg, path, demo=False, log=print):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, rel):
            full = os.path.normpath(os.path.join(STATIC, rel))
            if not full.startswith(STATIC) or not os.path.isfile(full):
                return self._json({"error": "not found"}, 404)
            ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                     ".svg": "image/svg+xml", ".png": "image/png",
                     ".webmanifest": "application/manifest+json", ".json": "application/json"}.get(os.path.splitext(full)[1], "application/octet-stream")
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            text = ctype.startswith("text/") or ctype.endswith("json")
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if text else ""))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        # ---------- доступ ----------
        def _external(self):
            """Запрос пришёл через туннель или не из домашней сети."""
            return bool(self.headers.get("Cf-Connecting-Ip") or self.headers.get("Cf-Ray")
                        or not _is_private(self.client_address[0]))

        def _authed(self):
            if not self._external():
                return True
            pw = cfg.get("password") or ""
            if not pw:
                return False  # снаружи без пароля не пускаем вообще
            c = SimpleCookie(self.headers.get("Cookie") or "")
            got = c["rtt"].value if "rtt" in c else ""
            return hmac.compare_digest(got, _token(pw))

        def _login_page(self, err="", code=200):
            body = LOGIN_PAGE.replace("%ERR%", err).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _deny(self, u):
            if u.path.startswith("/api/"):
                return self._json({"error": "нужен вход"}, 401)
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()

        def _do_login(self):
            n = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(n).decode("utf-8")) if n else {}
            given = (form.get("password") or [""])[0]
            pw = cfg.get("password") or ""
            if not pw or not hmac.compare_digest(given.encode(), pw.encode()):
                time.sleep(1.5)  # замедляем перебор
                return self._login_page("Неверный пароль" if pw else "Пароль не задан в config.json", 401)
            self.send_response(302)
            secure = "; Secure" if self._external() else ""
            self.send_header("Set-Cookie", f"rtt={_token(pw)}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax{secure}")
            self.send_header("Location", "/")
            self.end_headers()

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/login":
                return self._login_page()
            if u.path not in PUBLIC_PATHS and not self._authed():
                return self._deny(u)
            if u.path in ("/", "/index.html"):
                return self._file("index.html")
            if u.path in ("/manifest.webmanifest", "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"):
                return self._file(u.path.lstrip("/"))
            if u.path.startswith("/static/"):
                return self._file(u.path[len("/static/"):])
            con = db.connect(path)
            try:
                if u.path == "/api/status":
                    s = analytics.status(con)
                    s.update(demo=demo, collecting=collector.state["running"],
                             progress=collector.state["progress"],
                             manual_games=cfg.get("manual_games", []),
                             interval_minutes=cfg["interval_minutes"], domain=cfg["domain"],
                             public_url=None if self._external() else cfg.get("_public_url"))
                    return self._json(s)
                if u.path == "/api/games":
                    return self._json(analytics.games_table(con, cfg["new_game_days"]))
                if u.path.startswith("/api/game/"):
                    d = analytics.game_detail(con, int(u.path.rsplit("/", 1)[1]))
                    return self._json(d) if d else self._json({"error": "нет такой игры"}, 404)
                if u.path == "/api/trends":
                    return self._json(analytics.trends(con, int(q.get("days", 14)), cfg["new_game_days"]))
                if u.path == "/api/moves":
                    return self._json(analytics.rank_moves(con, int(q.get("hours", 6))))
                if u.path == "/api/updates":
                    return self._json(analytics.updates_feed(con, int(q.get("days", 28))))
                return self._json({"error": "not found"}, 404)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            finally:
                con.close()

        def do_POST(self):
            u = urlparse(self.path)
            if u.path == "/login":
                return self._do_login()
            if not self._authed():
                return self._deny(u)
            if u.path == "/api/collect":
                if demo:
                    return self._json({"ok": False, "message": "В демо-режиме сбор отключён."})
                if collector.state["running"]:
                    return self._json({"ok": True, "message": "Сбор уже идёт"})
                threading.Thread(target=collector.run_once, args=(cfg, path, log), daemon=True).start()
                return self._json({"ok": True, "message": "Сбор запущен"})
            if u.path in ("/api/manual/add", "/api/manual/remove"):
                entry = str(self._body().get("entry", "")).strip()
                lst = cfg.setdefault("manual_games", [])
                if u.path.endswith("add"):
                    if collector.parse_manual(entry)[0] is None:
                        return self._json({"ok": False, "message": "Нужна ссылка на игру, placeId или u:<universeId>"})
                    if entry not in lst:
                        lst.append(entry)
                elif entry in lst:
                    lst.remove(entry)
                if not demo:
                    config.save(cfg)
                return self._json({"ok": True, "manual_games": lst})
            return self._json({"error": "not found"}, 404)

    return Handler


def serve(cfg, path, demo=False, log=print):
    httpd = ThreadingHTTPServer((cfg.get("host") or "127.0.0.1", int(cfg["port"])),
                                make_handler(cfg, path, demo, log))
    return httpd
