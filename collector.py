"""Один проход сбора: топы + ручной список → детали игр → SQLite."""
import re
import threading
import time

import db
from roblox_api import RobloxAPI, is_restricted

_lock = threading.Lock()
state = {"running": False, "last_message": "", "progress": ""}

PLACE_URL = re.compile(r"roblox\.com/(?:[a-z-]+/)?games/(\d+)", re.I)


def parse_manual(entry):
    """Ссылка / placeId → ('place', id); 'u:123' → ('universe', id)."""
    s = str(entry).strip()
    m = PLACE_URL.search(s)
    if m:
        return "place", int(m.group(1))
    m = re.fullmatch(r"(?:u|universe)\s*:\s*(\d+)", s, re.I)
    if m:
        return "universe", int(m.group(1))
    if s.isdigit():
        return "place", int(s)
    return None, None


def resolve_manual(con, api, entries, log):
    ids = set()
    for e in entries:
        kind, val = parse_manual(e)
        if kind == "universe":
            ids.add(val)
        elif kind == "place":
            row = con.execute("SELECT universe_id FROM place_map WHERE place_id=?", (val,)).fetchone()
            if row:
                ids.add(row["universe_id"])
                continue
            try:
                uid = api.place_to_universe(val)
            except Exception as ex:
                log(f"  не удалось найти игру {e}: {ex}")
                continue
            if uid:
                con.execute("INSERT OR REPLACE INTO place_map VALUES(?,?)", (val, uid))
                ids.add(int(uid))
        else:
            log(f"  непонятная запись в manual_games: {e!r}")
    return ids


def run_once(cfg, path, log=print):
    if not _lock.acquire(blocking=False):
        log("Сбор уже идёт, пропускаю.")
        return False
    state["running"] = True
    started = int(time.time())
    con = db.connect(path)
    run_id = con.execute("INSERT INTO runs(started, ok) VALUES(?, 0)", (started,)).lastrowid
    con.commit()
    try:
        api = RobloxAPI(cfg["domain"], cfg["request_delay_seconds"], cfg["max_retries"], log=log)

        state["progress"] = "топы Роблокса"
        log(f"[{time.strftime('%H:%M:%S')}] Собираю топы с {api.domain} ...")
        top = api.explore_games(cfg["explore_max_games"], cfg["explore_pages_per_sort"])
        log(f"  в топах: {len(top)} игр")

        state["progress"] = "ручной список"
        manual = resolve_manual(con, api, cfg.get("manual_games") or [], log)
        con.commit()
        log(f"  ручной список: {len(manual)} игр")

        # Игры, которые уже отслеживаем, тоже продолжаем мерить (чтобы не было дыр в графиках).
        known = {r[0] for r in con.execute(
            "SELECT universe_id FROM games WHERE last_seen >= ?", (started - 30 * 86400,))}
        all_ids = set(top) | manual | known
        if not all_ids:
            raise RuntimeError(
                "Роблокс не отдал ни одной игры — похоже, данные скрыты для вашей страны. "
                "Нужен VPN с выходом в другой стране (Cloudflare WARP страну не меняет).")

        state["progress"] = f"детали {len(all_ids)} игр"
        log(f"  запрашиваю детали {len(all_ids)} игр ...")
        details = api.games(sorted(all_ids))
        good = [g for g in details if not is_restricted(g)]
        restricted = len(details) - len(good)
        if details and not good:
            raise RuntimeError(
                "Роблокс вернул заглушки «[TITLE UNAVAILABLE]» — данные скрыты для вашего региона/сети. "
                "Нужен VPN с выходом в другой стране (Cloudflare WARP страну не меняет).")
        if restricted:
            log(f"  скрыто Роблоксом: {restricted} игр (пропущены)")

        ts = started - started % 60
        con.execute("UPDATE games SET is_manual=0")
        n_updates = 0
        for g in good:
            uid = int(g["id"])
            name = g.get("name") or ""
            desc = g.get("description") or ""
            updated = g.get("updated") or ""
            in_top = uid in top
            old = con.execute("SELECT name, description, updated FROM games WHERE universe_id=?",
                              (uid,)).fetchone()
            if old and (old["name"] != name or old["description"] != desc or old["updated"] != updated):
                text_changed = old["name"] != name or old["description"] != desc
                # Некоторые игры публикуют версию каждые несколько минут. Такие «пустые» публикации
                # склеиваем: если последняя запись за 6 часов — тоже публикация, просто продлеваем её.
                last = con.execute("SELECT id, kind, ts FROM updates WHERE universe_id=? ORDER BY ts DESC LIMIT 1",
                                   (uid,)).fetchone()
                if not text_changed and last and last["kind"] == "publish" and ts - last["ts"] < 6 * 3600:
                    con.execute("UPDATE updates SET new_updated=? WHERE id=?", (updated, last["id"]))
                    old = None
            if old and (old["name"] != name or old["description"] != desc or old["updated"] != updated):
                con.execute(
                    "INSERT INTO updates(universe_id, ts, kind, old_name, new_name, old_description, "
                    "new_description, old_updated, new_updated) VALUES(?,?,?,?,?,?,?,?,?)",
                    (uid, ts, "text" if text_changed else "publish", old["name"], name,
                     old["description"], desc, old["updated"], updated))
                n_updates += 1
            sorts = ", ".join(sorted(top.get(uid, [])))
            creator = (g.get("creator") or {}).get("name")
            con.execute("""
                INSERT INTO games(universe_id, root_place_id, name, description, creator, updated, created,
                    visits, playing, favorites, first_seen, last_seen, first_seen_top, last_seen_top,
                    is_manual, sorts)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(universe_id) DO UPDATE SET
                    root_place_id=excluded.root_place_id, name=excluded.name,
                    description=excluded.description, creator=excluded.creator,
                    updated=excluded.updated, created=excluded.created, visits=excluded.visits,
                    playing=excluded.playing, favorites=excluded.favorites, last_seen=excluded.last_seen,
                    first_seen_top=COALESCE(games.first_seen_top, excluded.first_seen_top),
                    last_seen_top=COALESCE(excluded.last_seen_top, games.last_seen_top),
                    is_manual=excluded.is_manual,
                    sorts=CASE WHEN excluded.sorts != '' THEN excluded.sorts ELSE games.sorts END
            """, (uid, g.get("rootPlaceId"), name, desc, creator, updated, g.get("created"),
                  g.get("visits"), g.get("playing"), g.get("favoritedCount"), ts, ts,
                  ts if in_top else None, ts if in_top else None, 1 if uid in manual else 0, sorts))
            con.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?)",
                        (uid, ts, g.get("playing") or 0, g.get("visits") or 0))
        con.commit()

        con.execute("DELETE FROM snapshots WHERE ts < ?", (ts - 180 * 86400,))
        con.commit()

        state["progress"] = "лайки"
        for uid, (up, down) in api.votes([int(g["id"]) for g in good]).items():
            con.execute("UPDATE games SET up_votes=?, down_votes=? WHERE universe_id=?", (up, down, uid))
        for g in good:
            con.execute("UPDATE games SET genre=? WHERE universe_id=?", (g.get("genre"), int(g["id"])))
        con.commit()

        missing_icons = [r[0] for r in con.execute("SELECT universe_id FROM games WHERE icon_url IS NULL")]
        if missing_icons:
            state["progress"] = "иконки"
            for uid, url in api.icons(missing_icons).items():
                con.execute("UPDATE games SET icon_url=? WHERE universe_id=?", (url, uid))

        msg = (f"OK: {len(good)} игр, обновлений: {n_updates}, "
               f"запросов: {api.requests_made}, {int(time.time()) - started} c")
        con.execute("UPDATE runs SET finished=?, ok=1, games=?, restricted=?, message=? WHERE id=?",
                    (int(time.time()), len(good), restricted, msg, run_id))
        con.commit()
        log("  " + msg)
        state["last_message"] = msg
        return True
    except Exception as e:
        msg = f"Ошибка: {e}"
        con.execute("UPDATE runs SET finished=?, ok=0, message=? WHERE id=?",
                    (int(time.time()), msg, run_id))
        con.commit()
        log("  " + msg)
        state["last_message"] = msg
        return False
    finally:
        con.close()
        state["running"] = False
        state["progress"] = ""
        _lock.release()
