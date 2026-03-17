from __future__ import annotations
import os
import re
import json
import httpx
from fastapi import HTTPException
from backend.ai_secure import decrypt_api_key

def get_openai_model() -> str:
    """Returns the configured OpenAI model from environment variables."""
    return (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()

def strip_html(text: str) -> str:
    """Removes HTML tags for clean AI processing."""
    return re.sub(r"<[^>]+>", " ", text or "")

async def call_openai(user_api_key: str, system: str, user: str) -> str:
    """Standard non-streaming AI call for summaries and Q&A."""
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

async def call_clinical_intelligence(user_api_key: str, abstract: str, title: str) -> dict:
    """
    Phase 3 Intelligence: Extracts PICO, Stats, Bias, and Audience Rewrites.
    Forces JSON output for structured database storage in StudyMetrics.
    """
    system_prompt = """You are a senior clinical evidence appraiser. 
    Analyze the provided abstract and title. Return a valid JSON object with exactly these keys:
    1. pico: {population, intervention, comparator, outcome}
    2. stats: {sample_size: int, p_value, effect_size, confidence_interval, nnt_nnh}
    3. appraisal: {evidence_strength: int (1-5), bias_risk (Low/Mod/High), limitations: []}
    4. rewrites: {patient, clinician, student}
    Return JSON only. No prose outside the JSON structure."""

    user_content = f"Title: {title}\nAbstract: {abstract}"
    
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {user_api_key}", "Content-Type": "application/json"}
    payload = {
        "model": get_openai_model(),
        "temperature": 0.1, # Low temperature for extraction accuracy
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)
    
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=f"AI Intelligence Error: {r.text[:200]}")
    
    try:
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to parse structured clinical intelligence.")

def user_key_or_400(ai_key_enc: str | None) -> str:
    """Decrypts user key or raises error if missing."""
    if not ai_key_enc:
        raise HTTPException(status_code=400, detail="No AI key set. Go to AI page and add your key.")
    try:
        return decrypt_api_key(ai_key_enc)
    except Exception:
        raise HTTPException(status_code=400, detail="Stored AI key cannot be decrypted. Clear and re-set your key.")