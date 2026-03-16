from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("APP_ENV", "dev")
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # CORS
    cors_allow_origins: str = os.getenv("CORS_ALLOW_ORIGINS", "*")

    # Rate limit
    rate_limit_enabled: bool = _bool(os.getenv("RATE_LIMIT_ENABLED"), default=True)
    rate_limit_window_sec: int = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
    rate_limit_max_requests: int = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "120"))

    # JWT
    access_token_expire_hours: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "24"))

    # AI free tier limits
    gemini_free_daily_limit: int = int(os.getenv("GEMINI_FREE_DAILY_LIMIT", "20"))
    groq_free_daily_limit: int = int(os.getenv("GROQ_FREE_DAILY_LIMIT", "30"))

    # AI keys (free tier)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")

    # Semantic Scholar
    semantic_scholar_api_key: str = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

    # AI encryption
    ai_encryption_key: str = os.getenv("AI_ENCRYPTION_KEY", "")

    # Email config
    mail_enabled: bool = _bool(os.getenv("MAIL_ENABLED"), default=True)
    mail_from: str = os.getenv("MAIL_FROM", "noreply@seren.app")
    mail_username: str = os.getenv("MAIL_USERNAME", "")
    mail_password: str = os.getenv("MAIL_PASSWORD", "")
    mail_server: str = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    mail_port: int = int(os.getenv("MAIL_PORT", "587"))

    # Google OAuth
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
    )

    # Frontend URL (for email links)
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:5500")

    # Ollama
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3")


settings = Settings()