"""Шифрование данных паролем без сторонних библиотек.

AES-256-CTR (через утилиту openssl) + HMAC-SHA256, ключи из PBKDF2-SHA256.
Формат файла: 16 байт IV + шифротекст + 32 байта HMAC(IV + шифротекст).
Тот же формат расшифровывает браузер через WebCrypto (см. static/index.html).

  python vault.py enc <вход> <выход>     # пароль берётся из переменной SITE_PASSWORD
  python vault.py dec <вход> <выход>
"""
import hashlib
import hmac
import os
import shutil
import subprocess
import sys

SALT = b"roblox-trends/v1"
ITERATIONS = 300_000


def derive_key(password):
    """64 байта: 32 на шифрование + 32 на HMAC."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), SALT, ITERATIONS, 64)


def _openssl():
    exe = shutil.which("openssl")
    if not exe:
        for p in (r"C:\Program Files\Git\usr\bin\openssl.exe", r"C:\Program Files\Git\mingw64\bin\openssl.exe"):
            if os.path.exists(p):
                return p
        raise RuntimeError("Не найден openssl")
    return exe


def _ctr(key, iv, data):
    r = subprocess.run([_openssl(), "enc", "-aes-256-ctr", "-nosalt", "-K", key.hex(), "-iv", iv.hex()],
                       input=data, capture_output=True, check=True)
    return r.stdout


def encrypt(key, data):
    iv = os.urandom(16)
    ct = _ctr(key[:32], iv, data)
    tag = hmac.new(key[32:], iv + ct, hashlib.sha256).digest()
    return iv + ct + tag


def decrypt(key, blob):
    iv, ct, tag = blob[:16], blob[16:-32], blob[-32:]
    if not hmac.compare_digest(tag, hmac.new(key[32:], iv + ct, hashlib.sha256).digest()):
        raise ValueError("Неверный пароль или повреждённый файл")
    return _ctr(key[:32], iv, ct)


def password():
    pw = os.environ.get("SITE_PASSWORD", "")
    if not pw:
        sys.exit("Не задан SITE_PASSWORD")
    return pw


if __name__ == "__main__":
    mode, src, dst = sys.argv[1:4]
    key = derive_key(password())
    with open(src, "rb") as f:
        data = f.read()
    out = encrypt(key, data) if mode == "enc" else decrypt(key, data)
    with open(dst, "wb") as f:
        f.write(out)
    print(f"{mode}: {src} -> {dst} ({len(out)} байт)")
