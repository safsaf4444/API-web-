from __future__ import annotations

import os
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Core
from backend.core.errors import install_error_handlers
from backend.core.logging import install_logging
from backend.core.rate_limit import install_rate_limit
from backend.db import init_db

# Routers
from backend.routers.ai import router as ai_router
from backend.routers.auth import router as auth_router
from backend.routers.comments import router as comments_router
from backend.routers.external import router as external_router
from backend.routers.folders import router as folders_router
from backend.routers.health import router as health_router
from backend.routers.metrics import router as metrics_router
from backend.routers.studies import router as studies_router

logger = logging.getLogger("uvicorn")


# -----------------------------
# DB Init with Retry
# -----------------------------

def _safe_db_init():
    for i in range(5):
        try:
            logger.info(f"📡 DB Connection Attempt {i+1}/5")
            init_db()
            logger.info("✅ Database connected.")
            return
        except Exception as e:
            logger.warning(f"⚠️ DB not ready: {e}")
            time.sleep(2)

    logger.error("❌ Database failed to connect after retries")


# -----------------------------
# Secret Check
# -----------------------------

def _check_production_secrets():

    env = os.getenv("ENV", "dev").lower()
    secret = os.getenv("SECRET_KEY", "dev-secret-change-me")

    logger.info(f"🚀 Environment: {env}")

    if (env == "production" or os.getenv("RAILWAY_ENVIRONMENT")) and secret == "dev-secret-change-me":
        logger.error("❌ Default SECRET_KEY detected in production!")


# -----------------------------
# Lifespan
# -----------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):

    _check_production_secrets()

    try:
        _safe_db_init()
    except Exception as e:
        logger.error(f"DB init failed: {e}")

    yield

    logger.info("🛑 Application shutting down")


# -----------------------------
# FastAPI App
# -----------------------------

app = FastAPI(
    title="Medical Evidence API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)


# -----------------------------
# Install Core Services
# -----------------------------

install_error_handlers(app)
install_logging(app)
install_rate_limit(app)


# -----------------------------
# CORS
# -----------------------------

raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "").split(",")

allowed_origins = [
    "https://api-web-production-89b9.up.railway.app",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]

allowed_origins += [o.strip() for o in raw_origins if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Authorization"],
    max_age=86400,
)


# -----------------------------
# Routers
# -----------------------------

app.include_router(auth_router)
app.include_router(folders_router)
app.include_router(studies_router)
app.include_router(comments_router)
app.include_router(external_router)
app.include_router(ai_router)
app.include_router(metrics_router)
app.include_router(health_router)


# -----------------------------
# Static Files
# -----------------------------

if os.path.exists("frontend"):
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def serve_index():

    if os.path.exists("frontend/index.html"):
        return FileResponse("frontend/index.html")

    return {
        "status": "ok",
        "message": "Backend running but frontend missing",
        "docs": "/docs",
        "environment": os.getenv("ENV", "dev"),
    }


# -----------------------------
# Start Server
# -----------------------------

if __name__ == "__main__":

    import uvicorn

    port = int(os.getenv("PORT", 8000))

    logger.info(f"🌍 Starting server on port {port}")

    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )