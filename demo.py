"""Генератор демо-базы с вымышленными играми — чтобы посмотреть дашборд без реального сбора."""
import math
import os
import random
import time

import db

DAY, HOUR = 86400, 3600

# (название, базовый онлайн, сценарий, день события (дней назад), слово тренда)
GAMES = [
    ("Pet Meadow Simulator", 42000, "flat", None, None),
    ("Sky Island Tycoon", 18000, "decline", 20, None),
    ("Obby But Every Jump Grows", 9000, "verity", 13, "Verity"),
    ("Mega Tower Defense", 26000, "verity", 11, "Verity"),
    ("Blade Arena Legends", 31000, "verity", 15, "Verity"),
    ("Survive The Night Ward", 7000, "verity", 9, "Verity"),
    ("Fishing Frenzy Deluxe", 12000, "moon", 6, "Moonfruit"),
    ("Grow A Garden Classic", 55000, "moon", 8, "Moonfruit"),
    ("Brain Lab Escape", 4000, "new", 7, None),
    ("Taco Truck Tycoon", 2500, "new", 10, None),
    ("Rail Rush Racing", 15000, "decline", 12, None),
    ("Haunted Hotel Story", 8000, "season", 18, "Halloween"),
    ("Candy Corn Clicker", 3000, "season", 16, "Halloween"),
    ("Speed Run Galaxy", 11000, "flat", None, None),
    ("Dungeon Crawl Squad", 6000, "flat", None, None),
    ("Car Crusher Factory", 9500, "decline", 25, None),
    ("Ninja Parkour Dojo", 5200, "flat", None, None),
    ("Zombie Mall Defense", 14000, "spike", 3, None),
    ("Cozy Cafe Roleplay", 21000, "flat", None, None),
    ("Mining Depths", 7600, "decline", 8, None),
    ("Sword Forge Simulator", 4800, "verity", 5, "Verity"),
    ("Pirate Bay Battles", 6400, "flat", None, None),
    ("Bubble Pop Kingdom", 3900, "moon", 4, "Moonfruit"),
    ("Hide And Seek Ultra", 17000, "flat", None, None),
    ("Space Station Builder", 2100, "new", 5, None),
]

DESC_BASE = ("Welcome to {name}! Collect rare items, level up and team up with friends. "
             "Like the game and join the group for rewards. New codes every update!")
EVENT_TEXT = {
    "Verity": "🔮 NEW: Verity has arrived! Unlock Verity crystals and the Verity boss raid.",
    "Moonfruit": "🌙 Moonfruit event: harvest glowing Moonfruit and trade Moonfruit pets!",
    "Halloween": "🎃 Halloween update: spooky maps, candy hunt and Halloween skins!",
}


def _scenario(kind, days_ago_event, day_ago):
    """Множитель онлайна для момента «day_ago дней назад»."""
    if kind == "flat":
        return 1.0
    e = days_ago_event
    after = max(0.0, e - day_ago)  # сколько дней прошло после события
    if day_ago > e:
        return 1.0
    if kind in ("verity", "moon"):
        return 1 + 2.4 * (1 - math.exp(-after / 3))
    if kind == "decline":
        return max(0.35, 1 - 0.045 * after)
    if kind == "season":
        return 1 + 1.2 * (1 - math.exp(-after / 2))
    if kind == "spike":
        return 1 + 1.8 * math.exp(-after / 1.5) * (after > 0)
    if kind == "new":
        return 1 + 3.5 * (1 - math.exp(-after / 2.5))
    return 1.0


def build(root, days=35):
    path = os.path.join(root, "data", "demo.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    con = db.connect(path)
    rnd = random.Random(7)
    now = int(time.time()) // HOUR * HOUR
    start = now - days * DAY
    con.execute("INSERT INTO runs(started, finished, ok, games, restricted, message) VALUES(?,?,1,?,0,?)",
                (now, now, len(GAMES), "демо-данные"))

    for i, (name, base, kind, ev, word) in enumerate(GAMES):
        uid, place = 1000 + i, 9000 + i
        first_seen = start if kind != "new" else now - ev * DAY
        desc = DESC_BASE.format(name=name)
        cur_name, cur_desc = name, desc
        updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(first_seen - 3 * DAY))
        # плановые публикации версий
        publish_days = sorted(rnd.sample(range(1, days), 4))
        rows = []
        for ts in range(first_seen, now + 1, HOUR):
            day_ago = (now - ts) / DAY
            hour = time.gmtime(ts).tm_hour
            daily = 1 + 0.35 * math.sin((hour - 14) / 24 * 2 * math.pi)
            mult = _scenario(kind, ev, day_ago) if ev is not None else 1.0
            playing = int(base * mult * daily * rnd.uniform(0.92, 1.08))
            rows.append((uid, ts, playing, 0))
            day_idx = days - int(day_ago)
            if word and abs(day_ago - ev) < 0.5 / 24 and cur_desc == desc:
                new_desc = EVENT_TEXT[word] + "\n\n" + desc
                new_name = (f"[{word.upper()}] " + name) if kind in ("verity", "season") else name
                new_upd = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
                con.execute("INSERT INTO updates(universe_id, ts, kind, old_name, new_name, old_description,"
                            " new_description, old_updated, new_updated) VALUES(?,?,?,?,?,?,?,?,?)",
                            (uid, ts, "text", cur_name, new_name, cur_desc, new_desc, updated, new_upd))
                cur_name, cur_desc, updated = new_name, new_desc, new_upd
            elif ts % DAY == 0 and day_idx in publish_days:
                new_upd = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
                con.execute("INSERT INTO updates(universe_id, ts, kind, old_name, new_name, old_description,"
                            " new_description, old_updated, new_updated) VALUES(?,?,?,?,?,?,?,?,?)",
                            (uid, ts, "publish", cur_name, cur_name, cur_desc, cur_desc, updated, new_upd))
                updated = new_upd
        con.executemany("INSERT INTO snapshots VALUES(?,?,?,?)", rows)
        con.execute("""INSERT INTO games(universe_id, root_place_id, name, description, creator, updated,
                       created, visits, playing, favorites, first_seen, last_seen, first_seen_top,
                       last_seen_top, is_manual, sorts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, place, cur_name, cur_desc, f"Demo Studio {i % 6 + 1}", updated,
                     "2024-01-01T00:00:00Z", base * 9000, rows[-1][2], base * 40, first_seen, now,
                     first_seen, now, 1 if i in (5, 13) else 0, "Demo"))
    con.commit()
    con.close()
    return path
