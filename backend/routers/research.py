from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List, Dict, Any

from backend.database import get_session
from backend.models import User, ResearchQuestion
from backend.routers.auth import get_current_user

router = APIRouter(
    prefix="/research",
    tags=["Research Lifecycle"]
)

# Implementation will follow in Stage 3
