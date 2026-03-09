from __future__ import annotations

import os
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


# FIX: production secret guard — crashes loudly on startup if default key in prod
def _check_production_secrets() -> None:
    env = os.getenv("ENV", "dev").lower()
    secret = os.getenv("SECRET_KEY", "dev-secret-change-me")
    if env == "production" and secret == "dev-secret-change-me":
        raise RuntimeError(
            "SECRET_KEY is still the default dev value in a production environment. "
            "Set a real SECRET_KEY environment variable before deploying."
        )


# FIX: replaced deprecated @app.on_event("startup") with lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_production_secrets()
    init_db()
    yield


app = FastAPI(title="Medical Evidence API", lifespan=lifespan)

# FIX: wire all three middleware — previously none of these were being called
install_error_handlers(app)
install_logging(app)
install_rate_limit(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

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
    return {"status": "ok", "message": "Medical Evidence backend running"}