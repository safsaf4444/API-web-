from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.getenv("AI_ENCRYPTION_KEY")
    if key and key.strip():
        return Fernet(key.strip().encode("utf-8"))

    # Dev fallback: derive deterministic 32-byte key from SECRET_KEY (not for prod).
    secret = (os.getenv("SECRET_KEY") or "dev-secret-change-me").encode("utf-8")
    raw = (secret * 4)[:32]
    fkey = base64.urlsafe_b64encode(raw)
    return Fernet(fkey)


def encrypt_api_key(plain: str) -> str:
    f = _get_fernet()
    return f.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_api_key(enc: str) -> str:
    f = _get_fernet()
    return f.decrypt(enc.encode("utf-8")).decode("utf-8")


def mask_key(k: str) -> str:
    k = (k or "").strip()
    if len(k) <= 8:
        return "********"
    return k[:3] + "…" + k[-4:]
