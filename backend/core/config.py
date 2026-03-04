from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("APP_ENV", "dev")  # dev|prod
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # CORS
    cors_allow_origins: str = os.getenv("CORS_ALLOW_ORIGINS", "*")  # comma-separated or "*"

    # Rate limit (requests per window per IP)
    rate_limit_enabled: bool = _bool(os.getenv("RATE_LIMIT_ENABLED"), default=True)
    rate_limit_window_sec: int = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
    rate_limit_max_requests: int = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "120"))


settings = Settings()
