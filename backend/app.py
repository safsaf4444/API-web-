from __future__ import annotations

import os
import logging
import time
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Core imports
from backend.core.errors import install_error_handlers
from backend.core.logging import install_logging
from backend.core.rate_limit import install_rate_limit
from backend.db import init_db

# Router imports
from backend.routers.ai import router as ai_router
from backend.routers.auth import router as auth_router
from backend.routers.comments import router as comments_router
from backend.routers.external import router as external_router
from backend.routers.folders import router as folders_router
from backend.routers.health import router as health_router
from backend.routers.metrics import router as metrics_router
from backend.routers.studies import router as studies_router

logger = logging.getLogger("uvicorn")

def _safe_db_init():
    """Attempt to connect to DB with retries to prevent startup crashes."""
    for i in range(5):
        try:
            logger.info(f"📡 DB Connection Attempt {i+1}/5...")
            init_db()
            logger.info("✅ Database connected successfully.")
            return
        except Exception as e:
            logger.warning(f"⚠️ DB not ready yet: {e}")
            time.sleep(2)
    logger.error("❌ Failed to connect to DB after 5 attempts.")

def _check_production_secrets() -> None:
    env = os.getenv("ENV", "dev").lower()
    secret = os.getenv("SECRET_KEY", "dev-secret-change-me")
    
    logger.info(f"🚀 Starting app in {env} mode")
    
    # Critical check for Railway production environments
    if (env == "production" or os.getenv("RAILWAY_ENVIRONMENT")) and secret == "dev-secret-change-me":
        logger.error("❌ CRITICAL: Default SECRET_KEY used in production! Update Railway Variables.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_production_secrets()
    try:
        _safe_db_init()
    except Exception as e:
        logger.error(f"DB Init failed: {e}")
    yield
    logger.info("🛑 Shutting down...")

app = FastAPI(
    title="Medical Evidence API", 
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# 1. Install Core Services
install_error_handlers(app)
install_logging(app)
install_rate_limit(app)

# 2. Configure CORS
# Explicitly including your local dev port (5500) and Railway URL
raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
allowed_origins = [
    "https://api-web-production-89b9.up.railway.app",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
] + raw_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins, 
    allow_credentials=True, 
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Authorization"],
    max_age=86400,
)

# 3. Include Routers
app.include_router(auth_router)
app.include_router(folders_router)
app.include_router(studies_router)
app.include_router(comments_router)
app.include_router(external_router)
app.include_router(ai_router)
app.include_router(metrics_router)
app.include_router(health_router)

# 4. STATIC FILES & FRONTEND SERVING
if os.path.exists("frontend"):
    app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

@app.get("/")
async def serve_index():
    """Serve the main entry point index.html at the root URL."""
    if os.path.exists("frontend/index.html"):
        return FileResponse("frontend/index.html")
    return {
        "status": "ok", 
        "message": "Backend is running, but frontend/index.html was not found.",
        "environment": os.getenv("ENV", "dev"),
        "railway": bool(os.getenv("RAILWAY_ENVIRONMENT")),
        "docs": "/docs"
    }

# 5. SELF-START LOGIC (The "Genuine" Fix for the 502/Port Crash)
if __name__ == "__main__":
    import uvicorn
    # Grabs the Railway PORT variable or defaults to 8000 for local dev
    port = int(os.environ.get("PORT", 8000))
    # MUST be 0.0.0.0 to be accessible on Railway
    uvicorn.run(app, host="0.0.0.0", port=port)