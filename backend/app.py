from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.core.errors import install_error_handlers
from backend.core.logging import install_logging
from backend.core.rate_limit import install_rate_limit
from backend.db import init_db
from backend.routers.ai import router as ai_router
from backend.routers.auth import router as auth_router
from backend.routers.comments import router as comments_router
from backend.routers.community import router as community_router
from backend.routers.external import router as external_router
from backend.routers.folders import router as folders_router
from backend.routers.health import router as health_router
from backend.routers.metrics import router as metrics_router
from backend.routers.notebooks import router as notebooks_router
from backend.routers.extraction import router as extraction_router
from backend.routers.reviews import router as reviews_router
from backend.routers.studies import router as studies_router

logger = logging.getLogger("uvicorn")

FRONTEND_DIR = "frontend"


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


def _check_production_secrets():
    env    = os.getenv("ENV", "dev").lower()
    secret = os.getenv("SECRET_KEY", "dev-secret-change-me")
    db_url = os.getenv("DATABASE_URL", "")
    logger.info(f"🚀 Environment: {env}")
    if env == "production" or os.getenv("VERCEL"):
        if secret == "dev-secret-change-me":
            logger.error("❌ Default SECRET_KEY detected in production!")
        if "sqlite" in db_url or not db_url:
            logger.error("❌ Production requires a remote PostgreSQL database.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_production_secrets()
    try:
        _safe_db_init()
    except Exception as e:
        logger.error(f"DB init failed: {e}")
    yield
    logger.info("🛑 Application shutting down")


app = FastAPI(
    title="Seren Medical Evidence API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

install_error_handlers(app)
install_logging(app)
install_rate_limit(app)

# ── CORS ──────────────────────────────────────────────────────────────────────

raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "").split(",")

allowed_origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]

vercel_url = os.getenv("VERCEL_URL")
if vercel_url:
    allowed_origins.append(f"https://{vercel_url}")

allowed_origins += [o.strip() for o in raw_origins if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(allowed_origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Authorization"],
    max_age=86400,
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(folders_router)
app.include_router(studies_router)
app.include_router(comments_router)
app.include_router(external_router)
app.include_router(metrics_router)
app.include_router(health_router)
app.include_router(ai_router)
app.include_router(notebooks_router)   # Phase 4b
app.include_router(community_router)   # Phase 4b
app.include_router(reviews_router)     # Phase 4: Systematic Review Tooling
app.include_router(extraction_router)  # Phase 4c: Data Extraction

# ── Static ────────────────────────────────────────────────────────────────────

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    for name in ("favicon.svg", "favicon.ico"):
        p = os.path.join(FRONTEND_DIR, name)
        if os.path.exists(p):
            return FileResponse(p)
    return JSONResponse({"ok": True}, status_code=200)


@app.get("/", include_in_schema=False)
async def serve_index():
    path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"status": "ok", "docs": "/docs"})


_API_PREFIXES = (
    "/auth/", "/studies/", "/folders/", "/comments/",
    "/external/", "/metrics/", "/ai/", "/health",
    "/notebooks/", "/community/",
    "/reviews/", "/reminders/", "/extraction-templates/",
    "/docs", "/redoc", "/openapi",
)


@app.get("/{filename:path}", include_in_schema=False)
async def serve_frontend_file(filename: str):
    if any(f"/{filename}".startswith(p) for p in _API_PREFIXES):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    file_path = os.path.join(FRONTEND_DIR, filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    if "." not in filename.split("/")[-1]:
        index = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
    return JSONResponse({"detail": "Not Found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=False)