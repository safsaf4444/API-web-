from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List, Dict, Any

from backend.database import get_session
from backend.models import User
from backend.routers.auth import get_current_user

router = APIRouter(
    prefix="/ai/writing",
    tags=["Writing Support"]
)

# Implementation will follow in Stage 4
