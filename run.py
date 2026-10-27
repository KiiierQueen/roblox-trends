"""Roblox Trend Tracker — точка входа.

  python run.py            дашборд + сбор данных раз в час (одной командой)
  python run.py collect    один проход сбора и выход (для Планировщика заданий)
  python run.py serve      только дашборд, без сбора
  python run.py demo       дашборд на сгенерированных демо-данных
"""
import argparse
import sys
import threading
import time
import webbrowser

import collector
import config
import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg):
    print(msg, flush=True)


def lan_ip():
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # пакеты не отправляются, только выбор интерфейса
            return s.getsockname()[0]
    except OSError:
        return None


def start_tunnel(cfg):
    """Запускает Cloudflare quick tunnel и ждёт публичную ссылку."""
    import os
    import re
    import subprocess
    exe = os.path.join(config.ROOT, "tools", "cloudflared.exe")
    if not os.path.exists(exe):
        log("Туннель: нет tools/cloudflared.exe — публичной ссылки не будет (см. README).")
        return None
    if not cfg.get("password"):
        import secrets
        alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
        cfg["password"] = "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
        config.save({k: v for k, v in cfg.items() if not k.startswith("_")})
    proc = subprocess.Popen(
        [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{cfg['port']}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    found = threading.Event()

    def reader():
        for line in proc.stdout:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and not found.is_set():
                cfg["_public_url"] = m.group(0)
                with open(os.path.join(config.ROOT, "data", "public_url.txt"), "w", encoding="utf-8") as f:
                    f.write(m.group(0))
                found.set()
    threading.Thread(target=reader, daemon=True).start()
    if found.wait(40):
        log("")
        log("=" * 60)
        log(f"  Ссылка из любого места:  {cfg['_public_url']}")
        log(f"  Пароль:                  {cfg['password']}")
        log("  (ссылка меняется при каждом перезапуске трекера)")
        log("=" * 60)
        log("")
    else:
        log("Туннель: не удалось получить ссылку за 40 с (Cloudflare недоступен?). Работает только локально.")
    return proc


def scheduler(cfg, path, stop):
    interval = max(5, int(cfg["interval_minutes"])) * 60
    while not stop.is_set():
        con = db.connect(path)
        row = con.execute("SELECT started, ok FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        con.close()
        # после неудачи пробуем снова через 15 минут, а не каждую минуту
        last, ok = (row[0] or 0, row[1]) if row else (0, 1)
        wait = last + (interval if ok else min(interval, 15 * 60)) - time.time()
        if wait <= 0:
            collector.run_once(cfg, path, log)
            nxt = time.strftime("%H:%M", time.localtime(time.time() + interval))
            log(f"Следующий сбор примерно в {nxt}")
            wait = interval
        stop.wait(min(wait, 60))


def main():
    p = argparse.ArgumentParser(description="Трекер трендов Роблокса")
    p.add_argument("mode", nargs="?", default="run", choices=["run", "collect", "serve", "demo"])
    p.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    p.add_argument("--port", type=int)
    p.add_argument("--host", help="127.0.0.1 — только этот ПК, 0.0.0.0 — доступ из локальной сети")
    args = p.parse_args()

    cfg = config.load()
    if args.port:
        cfg["port"] = args.port
    if args.host:
        cfg["host"] = args.host
    path = config.db_path(cfg)

    if args.mode == "collect":
        ok = collector.run_once(cfg, path, log)
        sys.exit(0 if ok else 1)

    demo = args.mode == "demo"
    if demo:
        import demo as demo_mod
        path = demo_mod.build(config.ROOT)
        log(f"Демо-база: {path}")

    import server
    httpd = server.serve(cfg, path, demo=demo, log=log)
    url = f"http://127.0.0.1:{cfg['port']}/"
    log(f"Дашборд: {url}   (Ctrl+C — остановить)")
    if cfg.get("host") == "0.0.0.0":
        ip = lan_ip()
        if ip:
            log(f"С телефона (та же Wi-Fi сеть): http://{ip}:{cfg['port']}/")

    tunnel = start_tunnel(cfg) if cfg.get("public_tunnel") and not demo else None

    stop = threading.Event()
    if args.mode == "run":
        threading.Thread(target=scheduler, args=(cfg, path, stop), daemon=True).start()
        log(f"Сбор данных каждые {cfg['interval_minutes']} мин. Первый сбор начнётся сейчас.")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("Остановлено.")
    finally:
        stop.set()
        httpd.server_close()
        if tunnel:
            tunnel.terminate()


if __name__ == "__main__":
    main()
