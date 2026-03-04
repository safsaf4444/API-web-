from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import Folder, Study, User
from backend.schemas import FolderCreate, FolderPatch, FolderRead

router = APIRouter(tags=["folders"])


@router.get("/folders", response_model=List[FolderRead])
def list_folders(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    return session.exec(
        select(Folder).where(Folder.owner_username == current_user.username).order_by(Folder.name.asc())
    ).all()


@router.post("/folders", response_model=FolderRead)
def create_folder(
    payload: FolderCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name required")

    f = Folder(owner_username=current_user.username, name=name)
    session.add(f)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Folder already exists")

    session.refresh(f)
    return f


@router.patch("/folders/{folder_id}", response_model=FolderRead)
def rename_folder(
    folder_id: int,
    payload: FolderPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    f = session.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if f.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name required")

    existing = session.exec(
        select(Folder).where(Folder.owner_username == current_user.username, Folder.name == name, Folder.id != folder_id)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Folder already exists")

    f.name = name
    session.add(f)
    session.commit()
    session.refresh(f)
    return f


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    f = session.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if f.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    # unassign folder from user's studies
    studies = session.exec(
        select(Study).where(Study.owner_username == current_user.username, Study.folder_id == folder_id)
    ).all()
    for s in studies:
        s.folder_id = None
        session.add(s)

    session.delete(f)
    session.commit()
    return {"status": "deleted", "folder_id": folder_id}