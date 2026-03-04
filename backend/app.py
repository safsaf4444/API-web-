from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db import init_db
from backend.routers.ai import router as ai_router
from backend.routers.auth import router as auth_router
from backend.routers.comments import router as comments_router
from backend.routers.external import router as external_router
from backend.routers.folders import router as folders_router
from backend.routers.health import router as health_router  # ✅ NEW
from backend.routers.metrics import router as metrics_router
from backend.routers.studies import router as studies_router

app = FastAPI(title="Medical Evidence API")

# DEV CORS:
# - Explicit allow list (common)
# - Regex fallback (any localhost/127.0.0.1 port)
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
app.include_router(health_router)  # ✅ NEW


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def root():
    return {"status": "ok", "message": "Medical Evidence backend running"}