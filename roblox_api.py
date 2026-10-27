"""Клиент публичных API Роблокса с паузами между запросами и повторами.

Используемые эндпоинты (без авторизации):
  explore:   https://apis.<domain>/explore-api/v1/get-sorts
             https://apis.<domain>/explore-api/v1/get-sort-content
  игры:      https://games.<domain>/v1/games?universeIds=...   (до 50 id за запрос)
  place→uni: https://apis.<domain>/universes/v1/places/<placeId>/universe
  иконки:    https://thumbnails.<domain>/v1/games/icons?universeIds=...

Системные прокси (переменные HTTPS_PROXY / HTTP_PROXY) urllib подхватывает сам.
"""
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RobloxTrendTracker/1.0",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# Известные id подборок; дополнительно берутся все, что вернёт get-sorts.
KNOWN_SORTS = [
    "top-playing-now", "top-trending", "up-and-coming", "top-revisited",
    "top-earning", "top-rated", "fun-with-friends", "top-paid-access",
]

RESTRICTED_NAME = "[TITLE UNAVAILABLE]"


class RobloxAPI:
    def __init__(self, domain="roblox.com", delay=1.0, retries=5, timeout=25, log=print):
        self.domain = domain.strip().strip("/") or "roblox.com"
        self.delay = float(delay)
        self.retries = int(retries)
        self.timeout = timeout
        self.log = log
        self._last = 0.0
        self.requests_made = 0

    def url(self, sub, path, **params):
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return f"https://{sub}.{self.domain}{path}" + (f"?{q}" if q else "")

    def get(self, url):
        last_err = None
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.requests_made += 1
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (429, 500, 502, 503, 504):
                    ra = e.headers.get("Retry-After") if e.headers else None
                    pause = float(ra) if ra and ra.isdigit() else min(90, 3 * 2 ** attempt)
                    pause += random.random()
                    self.log(f"  HTTP {e.code}, повтор через {pause:.0f} c ({attempt + 1}/{self.retries})")
                    time.sleep(pause)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                last_err = e
                pause = min(60, 2 * 2 ** attempt) + random.random()
                self.log(f"  Сетевая ошибка: {e}; повтор через {pause:.0f} c")
                time.sleep(pause)
        raise RuntimeError(f"Не удалось получить {url}: {last_err}")

    # ---------- explore / discovery ----------
    def explore_games(self, max_games=300, pages_per_sort=3):
        """Возвращает {universe_id: set(названия подборок)} из рекомендаций Роблокса."""
        session = str(uuid.uuid4())
        found = {}
        sort_ids = []

        def add(games, sort_name):
            for g in games or []:
                uid = g.get("universeId") or g.get("universe_id")
                if uid:
                    found.setdefault(int(uid), set()).add(sort_name)

        token = None
        for _ in range(5):
            try:
                data = self.get(self.url("apis", "/explore-api/v1/get-sorts", sessionId=session,
                                         device="computer", country="all", sortsPageToken=token))
            except Exception as e:
                self.log(f"  get-sorts: {e}")
                break
            for s in data.get("sorts") or []:
                sid = s.get("sortId")
                if s.get("games"):
                    add(s["games"], s.get("sortDisplayName") or sid)
                if sid and (s.get("contentType") or "").lower() == "games":
                    sort_ids.append(sid)
            token = data.get("nextSortsPageToken")
            if not token:
                break

        for sid in dict.fromkeys(KNOWN_SORTS + sort_ids):
            if len(found) >= max_games:
                break
            page = None
            for _ in range(pages_per_sort):
                try:
                    data = self.get(self.url("apis", "/explore-api/v1/get-sort-content", sessionId=session,
                                             sortId=sid, device="computer", country="all", pageToken=page))
                except urllib.error.HTTPError as e:
                    if e.code not in (400, 404):
                        self.log(f"  {sid}: HTTP {e.code}")
                    break
                except Exception as e:
                    self.log(f"  {sid}: {e}")
                    break
                games = data.get("games") or []
                add(games, data.get("sortDisplayName") or sid)
                page = data.get("nextPageToken")
                if not games or not page:
                    break

        ids = list(found)[:max_games]
        return {i: found[i] for i in ids}

    # ---------- детали игр ----------
    def games(self, universe_ids):
        out = []
        ids = list(universe_ids)
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            data = self.get(self.url("games", "/v1/games", universeIds=",".join(map(str, chunk))))
            out.extend(data.get("data") or [])
        return out

    def place_to_universe(self, place_id):
        data = self.get(self.url("apis", f"/universes/v1/places/{int(place_id)}/universe"))
        return data.get("universeId")

    def icons(self, universe_ids):
        out = {}
        ids = list(universe_ids)
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            try:
                data = self.get(self.url("thumbnails", "/v1/games/icons",
                                         universeIds=",".join(map(str, chunk)), size="150x150",
                                         format="Png", isCircular="false", returnPolicy="PlaceHolder"))
            except Exception as e:
                self.log(f"  иконки: {e}")
                continue
            for d in data.get("data") or []:
                if d.get("imageUrl"):
                    out[int(d["targetId"])] = d["imageUrl"]
        return out


def is_restricted(game):
    return game.get("name") == RESTRICTED_NAME or (
        game.get("isContentRestricted") and not game.get("playing") and not game.get("visits"))
