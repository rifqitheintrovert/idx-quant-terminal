"""Enkripsi data dashboard (AES-256-GCM, kunci PBKDF2 dari username:password).
Repo & GitHub Pages bersifat publik, jadi login yang sungguhan = data dienkripsi;
tanpa username + password yang benar, isi latest.json tidak bisa dibaca."""
from __future__ import annotations

import base64
import hashlib
import json
import os

ITER = 200_000


def _key(username: str, password: str, salt: bytes, iters: int = ITER) -> bytes:
    secret = (username.strip().lower() + ":" + password).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", secret, salt, iters, 32)


def creds() -> tuple[str, str] | None:
    u, p = os.environ.get("APP_USERNAME", "").strip(), os.environ.get("APP_PASSWORD", "")
    return (u, p) if u and p else None


def encrypt(obj_json: str, username: str, password: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    # salt deterministik per username -> kunci tersimpan di browser tetap valid antar update
    salt = hashlib.sha256(("idxq-salt:" + username.strip().lower()).encode()).digest()[:16]
    iv = os.urandom(12)
    ct = AESGCM(_key(username, password, salt)).encrypt(iv, obj_json.encode("utf-8"), None)
    b = lambda x: base64.b64encode(x).decode()  # noqa: E731
    return {"enc": 1, "kdf": "PBKDF2-SHA256", "iter": ITER, "salt": b(salt), "iv": b(iv), "ct": b(ct)}


def decrypt(env: dict, username: str, password: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    d = base64.b64decode
    key = _key(username, password, d(env["salt"]), int(env.get("iter", ITER)))
    return json.loads(AESGCM(key).decrypt(d(env["iv"]), d(env["ct"]), None).decode("utf-8"))
