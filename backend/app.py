from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.errors import install_error_handlers
from backend.core.logging import install_logging
from backend.core.rate_limit import install_rate_limit
from backend.db import init_db
from backend.routers.ai import router as ai_router
from backend.routers.auth import router as auth_router
from backend.routers.comments import router as comments_router
from backend.routers.external import router as external_router
from backend.routers.folders import router as folders_router
from backend.routers.health import router as health_router
from backend.routers.metrics import router as metrics_router
from backend.routers.studies import router as studies_router

logger = logging.getLogger("uvicorn")

def _check_production_secrets() -> None:
    env = os.getenv("ENV", "dev").lower()
    secret = os.getenv("SECRET_KEY", "dev-secret-change-me")
    
    logger.info(f"🚀 Starting app in {env} mode")
    
    # Validation for Railway Production
    if (env == "production" or os.getenv("RAILWAY_ENVIRONMENT")) and secret == "dev-secret-change-me":
        logger.error("❌ CRITICAL: Default SECRET_KEY used in production!")
        raise RuntimeError("Set a real SECRET_KEY environment variable in Railway Settings.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_production_secrets()
    logger.info("📡 Initializing database connection...")
    init_db()
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

# 2. Configure CORS (Crucial for your Frontend to talk to Railway)
# allow_credentials must be True if you are sending JWTs via Cookies or Auth Headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For production, replace with your frontend URL
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

@app.get("/")
def root():
    return {
        "status": "ok", 
        "message": "Medical Evidence backend running",
        "environment": os.getenv("ENV", "dev"),
        "docs": "/docs"
    }