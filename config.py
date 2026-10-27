"""Настройки трекера (config.json рядом со скриптами)."""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")

DEFAULTS = {
    # Базовый домен API. По умолчанию официальный roblox.com.
    "domain": "roblox.com",
    # Как часто собирать данные, когда запущен `python run.py`.
    "interval_minutes": 60,
    # Пауза между запросами к API (секунды) и число повторов при ошибке.
    "request_delay_seconds": 1.0,
    "max_retries": 5,
    # Сколько игр максимум брать из рекомендаций/топов Роблокса.
    "explore_max_games": 300,
    "explore_pages_per_sort": 3,
    # Ваш ручной список: ссылки на игры, placeId или "u:<universeId>".
    "manual_games": [],
    # Игра считается «новой», если впервые попала в топ за последние N дней.
    "new_game_days": 14,
    # 127.0.0.1 — только этот компьютер; 0.0.0.0 — ещё и телефон в той же Wi-Fi сети.
    "host": "0.0.0.0",
    "port": 8765,
    # Публичная ссылка через Cloudflare-туннель (нужен tools/cloudflared.exe) и пароль для входа извне.
    "public_tunnel": False,
    "password": "",
    "db_path": "data/tracker.db",
}


def load():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        save(cfg)
    # Ручной список можно вести и в games.txt (одна ссылка/ID в строке) — удобно в GitHub.
    txt = os.path.join(ROOT, "games.txt")
    if os.path.exists(txt):
        with open(txt, encoding="utf-8") as f:
            extra = [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
        cfg["manual_games"] = list(dict.fromkeys(list(cfg.get("manual_games") or []) + extra))
    return cfg


def save(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def db_path(cfg):
    p = cfg["db_path"]
    return p if os.path.isabs(p) else os.path.join(ROOT, p)
