from __future__ import annotations

import os
import re

import httpx
from fastapi import HTTPException

from backend.ai_secure import decrypt_api_key


def get_openai_model() -> str:
    return (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


async def call_openai(user_api_key: str, system: str, user: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {user_api_key}", "Content-Type": "application/json"}
    payload = {
        "model": get_openai_model(),
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }

    async with httpx.AsyncClient(timeout=40.0) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="AI key rejected (401). Set a valid key in AI settings.")
    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="AI rate limit hit (429). Try again soon.")
    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"AI error HTTP {r.status_code}: {r.text[:300]}")

    data = r.json()
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        raise HTTPException(status_code=500, detail="AI response parse error")


def user_key_or_400(ai_key_enc: str | None) -> str:
    if not ai_key_enc:
        raise HTTPException(status_code=400, detail="No AI key set. Go to Info page and add your key.")
    try:
        return decrypt_api_key(ai_key_enc)
    except Exception:
        raise HTTPException(status_code=400, detail="Stored AI key cannot be decrypted. Clear and re-set your key.")
    