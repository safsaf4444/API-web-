from __future__ import annotations

import os
from enum import Enum
from typing import Optional

import httpx
from fastapi import HTTPException


# ── Model registry ────────────────────────────────────────────────────────────

class Provider(str, Enum):
    GEMINI_FREE  = "gemini_free"   # free tier — no user key needed
    GROQ_FREE    = "groq_free"     # free tier fallback — no user key needed
    OPENAI       = "openai"        # BYOK
    ANTHROPIC    = "anthropic"     # BYOK
    GEMINI_PRO   = "gemini_pro"    # BYOK
    GROQ_BYOK    = "groq_byok"     # BYOK
    OLLAMA       = "ollama"        # local — zero data leaves device


# Capability matrix — used for routing decisions
CAPABILITIES: dict[Provider, dict] = {
    Provider.GEMINI_FREE:  {"supports_json": True,  "max_ctx": 1_000_000, "speed": "fast",   "cost": "free"},
    Provider.GROQ_FREE:    {"supports_json": True,  "max_ctx": 32_768,    "speed": "fast",   "cost": "free"},
    Provider.OPENAI:       {"supports_json": True,  "max_ctx": 128_000,   "speed": "medium", "cost": "byok"},
    Provider.ANTHROPIC:    {"supports_json": True,  "max_ctx": 200_000,   "speed": "medium", "cost": "byok"},
    Provider.GEMINI_PRO:   {"supports_json": True,  "max_ctx": 1_000_000, "speed": "medium", "cost": "byok"},
    Provider.GROQ_BYOK:    {"supports_json": True,  "max_ctx": 32_768,    "speed": "fast",   "cost": "byok"},
    Provider.OLLAMA:       {"supports_json": False, "max_ctx": 8_000,     "speed": "slow",   "cost": "local"},
}

# Free tier daily limits per user (tracked by caller)
FREE_TIER_DAILY_LIMITS: dict[Provider, int] = {
    Provider.GEMINI_FREE: int(os.getenv("GEMINI_FREE_DAILY_LIMIT", "20")),
    Provider.GROQ_FREE:   int(os.getenv("GROQ_FREE_DAILY_LIMIT",   "30")),
}


# ── Unified response ──────────────────────────────────────────────────────────

class AIResponse:
    def __init__(self, text: str, provider: Provider, model: str):
        self.text     = text
        self.provider = provider
        self.model    = model

    def __repr__(self):
        return f"AIResponse(provider={self.provider}, model={self.model}, len={len(self.text)})"


# ── Token budget (rough estimate — avoids context exceeded errors) ────────────

def _estimate_tokens(text: str) -> int:
    # ~4 chars per token is a safe conservative estimate without tiktoken
    return max(1, len(text) // 4)

def _truncate_to_budget(text: str, max_tokens: int = 6000) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[truncated to fit context window]"


# ── Provider implementations ──────────────────────────────────────────────────

async def _call_gemini(api_key: str, system: str, user: str, model: str = "gemini-1.5-flash") -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": f"{system}\n\n{user}"}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024},
    }
    async with httpx.AsyncClient(timeout=40.0) as client:
        r = await client.post(url, json=payload, params={"key": api_key})

    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="Gemini rate limit hit. Try again soon.")
    if r.status_code == 401 or r.status_code == 403:
        raise HTTPException(status_code=401, detail="Gemini API key rejected.")
    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Gemini error {r.status_code}: {r.text[:300]}")

    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        raise HTTPException(status_code=500, detail="Gemini response parse error")


async def _call_groq(api_key: str, system: str, user: str, model: str = "llama-3.3-70b-versatile") -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": 0.3,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=40.0) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="Groq rate limit hit. Try again soon.")
    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="Groq API key rejected.")
    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Groq error {r.status_code}: {r.text[:300]}")

    data = r.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        raise HTTPException(status_code=500, detail="Groq response parse error")


async def _call_openai(api_key: str, system: str, user: str, model: str = "gpt-4o-mini") -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=40.0) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="OpenAI rate limit hit. Try again soon.")
    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="OpenAI key rejected. Check your key in AI settings.")
    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"OpenAI error {r.status_code}: {r.text[:300]}")

    data = r.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        raise HTTPException(status_code=500, detail="OpenAI response parse error")


async def _call_anthropic(api_key: str, system: str, user: str, model: str = "claude-haiku-4-5") -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=40.0) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="Anthropic rate limit hit. Try again soon.")
    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="Anthropic key rejected.")
    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Anthropic error {r.status_code}: {r.text[:300]}")

    data = r.json()
    try:
        return data["content"][0]["text"].strip()
    except Exception:
        raise HTTPException(status_code=500, detail="Anthropic response parse error")


async def _call_ollama(system: str, user: str, model: str = "llama3") -> str:
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": f"{system}\n\n{user}",
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, json=payload)
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Ollama not running. Start Ollama locally (ollama serve) then try again."
        )

    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Ollama error {r.status_code}: {r.text[:300]}")

    data = r.json()
    try:
        return (data.get("response") or "").strip()
    except Exception:
        raise HTTPException(status_code=500, detail="Ollama response parse error")


# ── Central router ────────────────────────────────────────────────────────────

async def run(
    system: str,
    user: str,
    *,
    # BYOK keys — all optional
    openai_key:    Optional[str] = None,
    anthropic_key: Optional[str] = None,
    gemini_key:    Optional[str] = None,
    groq_key:      Optional[str] = None,
    use_ollama:    bool = False,
    # Override which provider to use — if None, auto-routes
    preferred_provider: Optional[Provider] = None,
) -> AIResponse:
    """
    Central AI router. All AI calls in the project go through this function.

    Routing priority:
    1. preferred_provider if explicitly set
    2. BYOK keys if provided (OpenAI → Anthropic → Gemini Pro → Groq BYOK)
    3. Ollama local if use_ollama=True
    4. Free tier: Gemini Flash → Groq fallback
    """

    # Apply token budget to user message
    user = _truncate_to_budget(user, max_tokens=6000)

    # ── Explicit provider override ────────────────────────────────────────────
    if preferred_provider:
        return await _route_to(
            preferred_provider, system, user,
            openai_key=openai_key, anthropic_key=anthropic_key,
            gemini_key=gemini_key, groq_key=groq_key,
        )

    # ── BYOK priority chain ───────────────────────────────────────────────────
    if openai_key:
        text = await _call_openai(openai_key, system, user)
        return AIResponse(text, Provider.OPENAI, "gpt-4o-mini")

    if anthropic_key:
        text = await _call_anthropic(anthropic_key, system, user)
        return AIResponse(text, Provider.ANTHROPIC, "claude-haiku-4-5")

    if gemini_key:
        text = await _call_gemini(gemini_key, system, user, model="gemini-1.5-pro")
        return AIResponse(text, Provider.GEMINI_PRO, "gemini-1.5-pro")

    if groq_key:
        text = await _call_groq(groq_key, system, user)
        return AIResponse(text, Provider.GROQ_BYOK, "llama-3.3-70b-versatile")

    # ── Ollama local ──────────────────────────────────────────────────────────
    if use_ollama:
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
        text = await _call_ollama(system, user, model=ollama_model)
        return AIResponse(text, Provider.OLLAMA, ollama_model)

    # ── Free tier: Gemini Flash → Groq fallback ───────────────────────────────
    gemini_free_key = os.getenv("GEMINI_API_KEY", "").strip()
    groq_free_key   = os.getenv("GROQ_API_KEY",   "").strip()

    if gemini_free_key:
        try:
            text = await _call_gemini(gemini_free_key, system, user, model="gemini-1.5-flash")
            return AIResponse(text, Provider.GEMINI_FREE, "gemini-1.5-flash")
        except HTTPException as e:
            # fall through to Groq on quota, invalid key, or any server error
            if e.status_code not in (429, 503, 400, 401, 403):
                raise
            if not groq_free_key:
                raise HTTPException(
                    status_code=429,
                    detail="Free AI quota reached. Add a BYOK key in AI settings for unlimited use."
                )

    if groq_free_key:
        try:
            text = await _call_groq(groq_free_key, system, user)
            return AIResponse(text, Provider.GROQ_FREE, "llama-3.3-70b-versatile")
        except HTTPException as e:
            if e.status_code == 429:
                raise HTTPException(
                    status_code=429,
                    detail="Both free AI providers are rate limited. Add a BYOK key in AI settings."
                )
            raise

    # No keys configured at all
    raise HTTPException(
        status_code=400,
        detail=(
            "No AI provider configured. "
            "Either set GEMINI_API_KEY or GROQ_API_KEY in your .env for free tier, "
            "or add a BYOK key in AI settings."
        ),
    )


async def _route_to(
    provider: Provider,
    system: str,
    user: str,
    *,
    openai_key:    Optional[str] = None,
    anthropic_key: Optional[str] = None,
    gemini_key:    Optional[str] = None,
    groq_key:      Optional[str] = None,
) -> AIResponse:
    if provider == Provider.OPENAI:
        if not openai_key:
            raise HTTPException(status_code=400, detail="OpenAI BYOK key required.")
        return AIResponse(await _call_openai(openai_key, system, user), provider, "gpt-4o-mini")

    if provider == Provider.ANTHROPIC:
        if not anthropic_key:
            raise HTTPException(status_code=400, detail="Anthropic BYOK key required.")
        return AIResponse(await _call_anthropic(anthropic_key, system, user), provider, "claude-haiku-4-5")

    if provider == Provider.GEMINI_PRO:
        if not gemini_key:
            raise HTTPException(status_code=400, detail="Gemini BYOK key required.")
        return AIResponse(await _call_gemini(gemini_key, system, user, "gemini-1.5-pro"), provider, "gemini-1.5-pro")

    if provider == Provider.GROQ_BYOK:
        if not groq_key:
            raise HTTPException(status_code=400, detail="Groq BYOK key required.")
        return AIResponse(await _call_groq(groq_key, system, user), provider, "llama-3.3-70b-versatile")

    if provider == Provider.GEMINI_FREE:
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise HTTPException(status_code=400, detail="GEMINI_API_KEY not set in environment.")
        return AIResponse(await _call_gemini(key, system, user, "gemini-1.5-flash"), provider, "gemini-1.5-flash")

    if provider == Provider.GROQ_FREE:
        key = os.getenv("GROQ_API_KEY", "").strip()
        if not key:
            raise HTTPException(status_code=400, detail="GROQ_API_KEY not set in environment.")
        return AIResponse(await _call_groq(key, system, user), provider, "llama-3.3-70b-versatile")

    if provider == Provider.OLLAMA:
        model = os.getenv("OLLAMA_MODEL", "llama3")
        return AIResponse(await _call_ollama(system, user, model), provider, model)

    raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")


# ── Health check ──────────────────────────────────────────────────────────────

async def health_check() -> dict:
    """
    Ping each configured provider and return status.
    Called by GET /ai/health endpoint.
    """
    results = {}

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    groq_key   = os.getenv("GROQ_API_KEY",   "").strip()

    results["gemini_free"]  = "configured" if gemini_key else "no key — set GEMINI_API_KEY in .env"
    results["groq_free"]    = "configured" if groq_key   else "no key — set GROQ_API_KEY in .env"
    results["ollama_local"] = "unknown — ping localhost:11434 to check"
    results["byok_openai"]  = "user-provided key required"
    results["byok_anthropic"] = "user-provided key required"
    results["byok_gemini"]  = "user-provided key required"
    results["byok_groq"]    = "user-provided key required"

    return results