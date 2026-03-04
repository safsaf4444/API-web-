from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import Comment, Study, User
from backend.schemas import CommentCreate, CommentPatch

router = APIRouter(tags=["comments"])


@router.get("/studies/{study_id}/comments")
def list_comments(
    study_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=200, ge=1, le=500, description="Max comments to return"),
    offset: int = Query(default=0, ge=0, le=100000, description="Offset for pagination"),
):
    """List comments for a study.

    Backwards compatible: still returns a plain list.

    Notes:
    - v1 ordering: oldest -> newest (id asc)
    - pagination: limit/offset are applied to the full ordered list
    """

    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    stmt = (
        select(Comment)
        .where(Comment.study_id == study_id)
        .order_by(Comment.id.asc())
        .offset(offset)
        .limit(limit)
    )

    return session.exec(stmt).all()


@router.post("/studies/{study_id}/comments")
def add_comment(
    study_id: int,
    payload: CommentCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    parent_id = payload.parent_id
    if parent_id is not None:
        parent = session.get(Comment, parent_id)
        if not parent or parent.study_id != study_id:
            raise HTTPException(status_code=400, detail="Invalid parent_id")

    comment = Comment(
        study_id=study_id,
        parent_id=parent_id,
        author=current_user.username,
        body=payload.body,
    )
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


@router.patch("/comments/{comment_id}")
def edit_comment(
    comment_id: int,
    payload: CommentPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    c = session.get(Comment, comment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Comment not found")

    study = session.get(Study, c.study_id)
    if not study or study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    if c.author != current_user.username:
        raise HTTPException(status_code=403, detail="Only the author can edit this comment")

    c.body = payload.body
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    c = session.get(Comment, comment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Comment not found")

    study = session.get(Study, c.study_id)
    if not study or study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    if c.author != current_user.username:
        raise HTTPException(status_code=403, detail="Only the author can delete this comment")

    # delete replies recursively (simple approach for v1: delete all descendants by repeated passes)
    to_delete = [c.id]
    changed = True
    while changed:
        changed = False
        kids = session.exec(select(Comment).where(Comment.parent_id.in_(to_delete))).all()
        for k in kids:
            if k.id not in to_delete:
                to_delete.append(k.id)
                changed = True

    for cid in reversed(to_delete):
        obj = session.get(Comment, cid)
        if obj:
            session.delete(obj)

    session.commit()
    return {"status": "deleted", "comment_id": comment_id}