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

# Setup basic logging to ensure we see startup messages in Railway logs
logger = logging.getLogger("uvicorn")

def _check_production_secrets() -> None:
    env = os.getenv("ENV", "dev").lower()
    secret = os.getenv("SECRET_KEY", "dev-secret-change-me")
    
    logger.info(f"Starting app in {env} mode")
    
    if env == "production" and secret == "dev-secret-change-me":
        logger.error("CRITICAL: Default SECRET_KEY used in production!")
        raise RuntimeError(
            "SECRET_KEY is still the default dev value in a production environment. "
            "Set a real SECRET_KEY environment variable before deploying."
        )

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Run safety checks
    _check_production_secrets()
    # 2. Initialize Database
    logger.info("Initializing database connection...")
    init_db()
    logger.info("Database initialized successfully.")
    yield
    logger.info("Shutting down...")

app = FastAPI(
    title="Medical Evidence API", 
    lifespan=lifespan,
    # This ensures the docs are always available at /docs
    docs_url="/docs",
    redoc_url="/redoc"
)

# Wire middleware
install_error_handlers(app)
install_logging(app)
install_rate_limit(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

# Include routers
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
        "environment": os.getenv("ENV", "dev")
    }