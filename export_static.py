"""Выгружает базу в статичный сайт (для GitHub Pages): JSON-файлы + дашборд.

  python export_static.py site
"""
import json
import os
import shutil
import sys
import time

import analytics
import config
import db
import vault

DAY = 86400
KEEP_DAYS = 366  # сколько дней истории отдавать на графики (вся хранимая история)


# Если задан SITE_PASSWORD — все данные шифруются, сайт спросит пароль.
KEY = None


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if KEY:
        with open(path[:-5] + ".bin", "wb") as f:
            f.write(vault.encrypt(KEY, raw))
    else:
        with open(path, "wb") as f:
            f.write(raw)


def main(out):
    global KEY
    pw = os.environ.get("SITE_PASSWORD", "")
    KEY = vault.derive_key(pw) if pw else None
    cfg = config.load()
    con = db.connect(config.db_path(cfg))
    if os.path.exists(out):
        shutil.rmtree(out)
    data = os.path.join(out, "data")
    os.makedirs(os.path.join(data, "game"))
    with open(os.path.join(data, "auth.json"), "w", encoding="utf-8") as f:
        json.dump({"encrypted": bool(KEY), "salt": vault.SALT.decode(), "iterations": vault.ITERATIONS}, f)

    status = analytics.status(con)
    status.update(static=True, demo=False, collecting=False, progress="", manual_games=[],
                  interval_minutes=cfg["interval_minutes"], domain=cfg["domain"],
                  exported=int(time.time()))
    dump(os.path.join(data, "status.json"), status)
    games = analytics.games_table(con, cfg["new_game_days"])
    dump(os.path.join(data, "games.json"), games)
    for d in (7, 14, 28):
        dump(os.path.join(data, f"trends_{d}.json"), analytics.trends(con, d, cfg["new_game_days"]))
    dump(os.path.join(data, "updates.json"), analytics.updates_feed(con, 28))

    now = status["now"] or 0
    for g in games:
        d = analytics.game_detail(con, g["id"])
        d["snapshots"] = [s for s in d["snapshots"] if s[0] >= now - KEEP_DAYS * DAY]
        dump(os.path.join(data, "game", f"{g['id']}.json"), d)

    static = os.path.join(config.ROOT, "static")
    for name in os.listdir(static):
        if name != "index.html":
            shutil.copy(os.path.join(static, name), out)
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    html = html.replace("<head>", "<head>\n<script>window.STATIC_MODE = true;</script>", 1)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(out, ".nojekyll"), "w") as f:
        f.write("")
    print(f"Сайт выгружен в {out}: {len(games)} игр" + (", данные зашифрованы" if KEY else ""))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "site")
