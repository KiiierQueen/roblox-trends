"""Скачивает свежую базу с GitHub и расшифровывает её в data/tracker.db — для анализа.

  python download_db.py                 # спросит пароль
  python download_db.py --repo user/roblox-trends
Пароль можно передать через переменную SITE_PASSWORD.
"""
import argparse
import getpass
import gzip
import os
import sys
import urllib.request

import config
import vault

DEFAULT_REPO = "KiiierQueen/roblox-trends"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--out", default=os.path.join(config.ROOT, "data", "tracker.db"))
    a = p.parse_args()

    url = f"https://raw.githubusercontent.com/{a.repo}/data/tracker.db.gz.enc"
    print(f"Скачиваю {url} ...")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "rtt"}), timeout=60) as r:
        blob = r.read()
    pw = os.environ.get("SITE_PASSWORD") or getpass.getpass("Пароль: ")
    try:
        raw = gzip.decompress(vault.decrypt(vault.derive_key(pw), blob))
    except ValueError:
        sys.exit("Неверный пароль.")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(a.out + suffix):
            os.remove(a.out + suffix)
    with open(a.out, "wb") as f:
        f.write(raw)
    print(f"Готово: {a.out} ({len(raw) / 1e6:.1f} МБ)")


if __name__ == "__main__":
    main()
