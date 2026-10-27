"""Расчёт роста онлайна, «новых» игр и трендовых слов."""
import math
import re
from collections import defaultdict

DAY = 86400

# Рост = средний онлайн за последние 24 ч  /  средний онлайн за сутки вокруг точки «N дней назад».
# Сравнение суточных средних убирает суточные колебания (ночью онлайн всегда ниже).


def _avg(points, a, b):
    vals = [p for t, p in points if a <= t <= b]
    return sum(vals) / len(vals) if vals else None


def growth(points, now, days):
    recent = _avg(points, now - DAY, now)
    center = now - days * DAY
    past = _avg(points, center - DAY / 2, center + DAY / 2)
    if recent is None or past is None:
        return None
    if past <= 0:
        return {"ratio": None, "pct": None, "from": 0, "to": round(recent)}
    ratio = recent / past
    return {"ratio": round(ratio, 3), "pct": round((ratio - 1) * 100, 1),
            "from": round(past), "to": round(recent)}


def growth_1d(points, now):
    """Сутки к суткам: последние 3 часа против тех же 3 часов вчера."""
    recent = _avg(points, now - 3 * 3600, now)
    past = _avg(points, now - DAY - 3 * 3600, now - DAY + 1800)
    if recent is None or past is None:
        return None
    if past <= 0:
        return {"ratio": None, "pct": None, "from": 0, "to": round(recent)}
    ratio = recent / past
    return {"ratio": round(ratio, 3), "pct": round((ratio - 1) * 100, 1),
            "from": round(past), "to": round(recent)}


def _iso_ts(s):
    from datetime import datetime, timezone
    if not s:
        return None
    try:
        return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def _now(con):
    row = con.execute("SELECT MAX(ts) FROM snapshots").fetchone()
    return row[0]


def status(con):
    now = _now(con)
    first = con.execute("SELECT MIN(ts) FROM snapshots").fetchone()[0]
    runs = [dict(r) for r in con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 5")]
    return {
        "now": now, "first": first,
        "games": con.execute("SELECT COUNT(*) FROM games").fetchone()[0],
        "snapshots": con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        "updates": con.execute("SELECT COUNT(*) FROM updates WHERE kind='text'").fetchone()[0],
        "runs": runs,
    }


def games_table(con, new_days=14):
    now = _now(con)
    if not now:
        return []
    first_ts = con.execute("SELECT MIN(ts) FROM snapshots").fetchone()[0]
    series = defaultdict(list)
    for uid, ts, playing in con.execute(
            "SELECT universe_id, ts, playing FROM snapshots WHERE ts >= ? ORDER BY ts", (now - 30 * DAY,)):
        series[uid].append((ts, playing))

    last_text = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT universe_id, MAX(ts), COUNT(*) FROM updates WHERE kind='text' AND ts >= ? "
        "GROUP BY universe_id", (now - 28 * DAY,))}

    out = []
    for g in con.execute("SELECT * FROM games"):
        uid = g["universe_id"]
        pts = series.get(uid, [])
        if not pts:
            continue
        # Спарклайн: средний онлайн по суткам за 28 дней.
        sums, cnts = [0] * 28, [0] * 28
        for t, p in pts:
            d = int((now - t) // DAY)
            if 0 <= d < 28:
                sums[27 - d] += p
                cnts[27 - d] += 1
        spark = [round(s / c) if c else None for s, c in zip(sums, cnts)]
        span_days = (now - pts[0][0]) / DAY
        g1 = growth_1d(pts, now)
        g7, g14, g28 = growth(pts, now, 7), growth(pts, now, 14), growth(pts, now, 28)
        created_ts = _iso_ts(g["created"])
        up, down = g["up_votes"] or 0, g["down_votes"] or 0
        # «Лучший доступный» рост для трендов, пока история короткая.
        best = g14 or g7 or g1
        if best is None and span_days >= 2:
            first_avg = _avg(pts, pts[0][0], pts[0][0] + DAY / 2)
            recent = _avg(pts, now - DAY / 2, now)
            if first_avg and recent is not None:
                best = {"ratio": round(recent / first_avg, 3),
                        "pct": round((recent / first_avg - 1) * 100, 1)}
        fst = g["first_seen_top"]
        is_new = bool(fst and fst >= first_ts + DAY and fst >= now - new_days * DAY)
        lt = last_text.get(uid)
        out.append({
            "id": uid, "place_id": g["root_place_id"], "name": g["name"], "creator": g["creator"],
            "desc": (g["description"] or "")[:1500],
            "icon": g["icon_url"], "online": pts[-1][1], "online_ts": pts[-1][0],
            "visits": g["visits"], "favorites": g["favorites"],
            "updated": g["updated"], "created": g["created"],
            "g1": g1, "g7": g7, "g14": g14, "g28": g28, "best": best,
            "age_days": round((now - created_ts) / DAY) if created_ts else None,
            "rating": round(up / (up + down) * 100) if up + down >= 20 else None,
            "votes": up + down, "genre": g["genre"],
            "first_seen_top": fst, "is_new": is_new, "is_manual": bool(g["is_manual"]),
            "in_top_now": g["last_seen_top"] == now, "sorts": g["sorts"],
            "text_updates_28d": lt[1] if lt else 0, "last_text_update": lt[0] if lt else None,
            "spark": spark, "history_days": round(span_days, 1),
        })
    return out


def game_detail(con, uid):
    g = con.execute("SELECT * FROM games WHERE universe_id=?", (uid,)).fetchone()
    if not g:
        return None
    snaps = [[t, p] for t, p in con.execute(
        "SELECT ts, playing FROM snapshots WHERE universe_id=? ORDER BY ts", (uid,))]
    ups = [dict(r) for r in con.execute(
        "SELECT * FROM updates WHERE universe_id=? ORDER BY ts DESC", (uid,))]
    return {"game": dict(g), "snapshots": snaps, "updates": ups}


def updates_feed(con, days=28, limit=300):
    now = _now(con) or 0
    rows = con.execute("""
        SELECT u.*, g.name AS game_name, g.icon_url, g.playing
        FROM updates u JOIN games g ON g.universe_id = u.universe_id
        WHERE u.kind='text' AND u.ts >= ? ORDER BY u.ts DESC LIMIT ?""", (now - days * DAY, limit))
    return [dict(r) for r in rows]


# ---------------- Тренды по словам ----------------
STOP = set("""
a an the and or of to in on for with at by from is are be was were it its this that these those you your
we our us they them their he she his her i me my all any can will just get got more most new now out up
so if as not no do does did has have had than then too very there here what when who how why which into
over about after before also only one two three per off via
game games roblox robloxian rblx play playing played player players join group like likes favorite
favourite fav update updates updated codes code free discord server servers version ver beta alpha
please thanks thank enjoy fun best top official event events released release added fixed fix fixes bug
bugs soon coming today week weekly daily use make made build built
и в во не на с со что как а но да по к ко из у о об от до за для это этот эта эти то же или ли бы
вы мы ты он она они его её их наш ваш все всё так уже еще ещё при без над под про игра игру игры
игре обновление обновления новый новая новые теперь
""".split())

TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def tokens(text):
    out = set()
    for t in TOKEN.findall((text or "").lower()):
        if len(t) < 3 or t.isdigit() or t in STOP or not re.search(r"[^\W\d_]", t):
            continue
        out.add(t)
    return out


def _snippet(text, word, width=70):
    if not text:
        return ""
    m = re.search(re.escape(word), text, re.I)
    if not m:
        return ""
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    s = text[a:b].replace("\n", " ")
    return ("…" if a else "") + s + ("…" if b < len(text) else "")


def trends(con, days=14, new_days=14):
    table = games_table(con, new_days)
    now = _now(con) or 0
    by_id = {g["id"]: g for g in table}

    def ratio(g):
        r = (g["best"] or {}).get("ratio")
        return r if r else 0

    growing = sorted([g for g in table if ratio(g) >= 1.25 and g["online"] >= 50],
                     key=ratio, reverse=True)[:60]
    relaxed = False
    if len(growing) < 5:
        growing = sorted([g for g in table if ratio(g) >= 1.05], key=ratio, reverse=True)[:60]
        relaxed = True

    texts = {r[0]: (r[1] or "", r[2] or "") for r in con.execute(
        "SELECT universe_id, name, description FROM games")}
    word_games = defaultdict(set)
    for uid, (name, desc) in texts.items():
        if uid in by_id:
            for w in tokens(name) | tokens(desc):
                word_games[w].add(uid)

    grow_ids = {g["id"] for g in growing}
    n_all, n_grow = max(1, len(by_id)), max(1, len(grow_ids))
    words = []
    for w, ids in word_games.items():
        hit = ids & grow_ids
        if len(hit) < 2:
            continue
        lift = (len(hit) / n_grow) / ((len(ids) + 1) / (n_all + 1))
        if lift < 1.2:
            continue
        in_names = sum(1 for i in hit if w in tokens(texts[i][0]))
        score = lift * math.log2(1 + len(hit)) * (1 + in_names / len(hit))
        examples = sorted(hit, key=lambda i: ratio(by_id[i]), reverse=True)[:8]
        words.append({
            "word": w, "score": round(score, 2), "lift": round(lift, 2),
            "growing_games": len(hit), "all_games": len(ids), "in_names": in_names,
            "games": [{"id": i, "name": by_id[i]["name"], "ratio": ratio(by_id[i]),
                       "online": by_id[i]["online"]} for i in examples],
        })
    words.sort(key=lambda x: x["score"], reverse=True)

    # Новые слова, появившиеся в названиях/описаниях при обновлениях за период.
    upd_words = defaultdict(lambda: {"games": {}, "last": 0, "in_names": set()})
    for u in con.execute("SELECT * FROM updates WHERE kind='text' AND ts >= ? ORDER BY ts",
                         (now - days * DAY,)):
        added = (tokens(u["new_name"]) | tokens(u["new_description"])) - \
                (tokens(u["old_name"]) | tokens(u["old_description"]))
        name_added = tokens(u["new_name"]) - tokens(u["old_name"])
        for w in added:
            e = upd_words[w]
            if w in name_added:
                e["in_names"].add(u["universe_id"])
            e["last"] = max(e["last"], u["ts"])
            e["games"][u["universe_id"]] = {
                "id": u["universe_id"], "name": u["new_name"], "ts": u["ts"],
                "snippet": _snippet(u["new_description"], w) or _snippet(u["new_name"], w),
            }
    fresh = []
    for w, e in upd_words.items():
        gs = list(e["games"].values())
        weight = sum(max(1.0, ratio(by_id[g["id"]])) if g["id"] in by_id else 1.0 for g in gs)
        for g in gs:
            gg = by_id.get(g["id"])
            g["ratio"] = ratio(gg) if gg else None
            g["online"] = gg["online"] if gg else None
        gs.sort(key=lambda g: g["ratio"] or 0, reverse=True)
        fresh.append({"word": w, "games_count": len(gs), "in_names": len(e["in_names"]),
                      "score": round(weight, 2), "last": e["last"], "games": gs[:8]})
    fresh.sort(key=lambda x: (x["games_count"], x["in_names"], x["score"]), reverse=True)

    return {
        "days": days, "relaxed": relaxed,
        "growing": [{"id": g["id"], "name": g["name"], "ratio": ratio(g), "online": g["online"],
                     "icon": g["icon"]} for g in growing[:25]],
        "words": words[:80], "update_words": fresh[:80],
    }
