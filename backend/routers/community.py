from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func

from backend.db import get_session
from backend.models import (
    Bookmark, Comment, CommunityPost, CommunityReply,
    CommunityUpvote, Study, StudyMetrics, User
)
from typing import Optional as _Opt
from fastapi import Header as _Header
from backend.routers.auth import get_current_user
import os as _os

async def optional_user(authorization: _Opt[str] = _Header(default=None)) -> _Opt[str]:
    """Return username from Bearer token if valid, else None. Never raises."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1]
    try:
        from jose import jwt as _jwt, JWTError
        secret    = _os.getenv("SECRET_KEY", "dev-secret-change-me")
        algorithm = _os.getenv("ALGORITHM", "HS256")
        payload   = _jwt.decode(token, secret, algorithms=[algorithm])
        return payload.get("sub")
    except Exception:
        return None

from backend.schemas import (
    BookmarkRead, CommunityPostCreate, CommunityPostPatch, CommunityPostRead,
    CommunityReplyCreate, CommunityReplyPatch, CommunityReplyRead,
    LandingStats, PaperOfDay, TrendingTopic,
)

router = APIRouter(prefix="/community", tags=["community"])

_TOPIC_KEYWORDS = {
    "Cardiology":            ["heart", "cardiac", "myocardial", "coronary", "atrial", "ventricular", "hypertension"],
    "Oncology":              ["cancer", "tumour", "tumor", "chemotherapy", "oncolog", "carcinoma", "malignant"],
    "Neurology":             ["stroke", "neurolog", "alzheimer", "parkinson", "dementia", "epilepsy", "brain"],
    "Respiratory":           ["copd", "asthma", "pneumonia", "respiratory", "lung", "bronch", "pulmonary"],
    "Endocrinology":         ["diabetes", "insulin", "thyroid", "endocrine", "glucose", "obesity", "metabolic"],
    "Infectious Disease":    ["infection", "antibiotic", "viral", "bacterial", "sepsis", "hiv", "covid", "pandemic"],
    "Surgery":               ["surgical", "surgery", "operative", "laparoscop", "resection", "anastomosis"],
    "Pharmacology":          ["drug", "medication", "pharmacol", "dosage", "adverse effect", "pharmacokinetic"],
    "Mental Health":         ["depression", "anxiety", "psychiatric", "mental health", "psychosis", "schizophrenia"],
    "Paediatrics":           ["paediatric", "pediatric", "child", "infant", "neonatal", "adolescent"],
    "Evidence-Based Medicine": ["meta-analysis", "systematic review", "rct", "randomised", "evidence", "cochrane"],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _author_display(post_or_reply) -> Optional[str]:
    if post_or_reply.is_anonymous:
        return None
    return post_or_reply.author


def _enrich_post(post: CommunityPost, session: Session, username: Optional[str] = None) -> CommunityPostRead:
    user_upvoted = False
    user_bookmarked = False
    study_title = None

    if username:
        up = session.exec(
            select(CommunityUpvote).where(
                CommunityUpvote.username == username,
                CommunityUpvote.target_id == post.id,
                CommunityUpvote.target_type == "post",
            )
        ).first()
        user_upvoted = up is not None

        bm = session.exec(
            select(Bookmark).where(
                Bookmark.owner_username == username,
                Bookmark.target_id == post.id,
                Bookmark.target_type == "post",
            )
        ).first()
        user_bookmarked = bm is not None

    if post.study_id:
        study = session.get(Study, post.study_id)
        if study:
            study_title = study.title

    out = CommunityPostRead.model_validate(post)
    out.author = _author_display(post)
    out.user_upvoted = user_upvoted
    out.user_bookmarked = user_bookmarked
    out.study_title = study_title
    return out


def _build_reply_tree(replies: List[CommunityReply], session: Session, username: Optional[str]) -> List[CommunityReplyRead]:
    """Build nested reply tree from flat list."""
    by_id = {}
    roots = []

    for r in replies:
        out = CommunityReplyRead.model_validate(r)
        out.author = _author_display(r)
        if username:
            up = session.exec(
                select(CommunityUpvote).where(
                    CommunityUpvote.username == username,
                    CommunityUpvote.target_id == r.id,
                    CommunityUpvote.target_type == "reply",
                )
            ).first()
            out.user_upvoted = up is not None
            bm = session.exec(
                select(Bookmark).where(
                    Bookmark.owner_username == username,
                    Bookmark.target_id == r.id,
                    Bookmark.target_type == "reply",
                )
            ).first()
            out.user_bookmarked = bm is not None
        by_id[r.id] = out

    for r in replies:
        if r.parent_reply_id and r.parent_reply_id in by_id:
            by_id[r.parent_reply_id].replies.append(by_id[r.id])
        else:
            roots.append(by_id[r.id])

    return roots


# ── Discovery / Landing (MOVED TO TOP) ────────────────────────────────────────

@router.get("/trending", response_model=List[TrendingTopic])
def trending_topics(
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(optional_user),
):
    """Aggregate trending topics from community post titles + bodies."""
    posts = list(session.exec(
        select(CommunityPost)
        .where(CommunityPost.is_deleted == False)
        .order_by(CommunityPost.created_at.desc())
        .limit(200)
    ).all())

    counts: dict[str, int] = {t: 0 for t in _TOPIC_KEYWORDS}
    for post in posts:
        text = (post.title + " " + post.body).lower()
        for topic, keywords in _TOPIC_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                counts[topic] += 1

    # Also count tags
    tag_counts: dict[str, int] = {}
    for post in posts:
        if post.tags:
            for tag in post.tags.split(","):
                t = tag.strip()
                if t:
                    tag_counts[t] = tag_counts.get(t, 0) + 1

    merged = {**counts}
    for t, c in tag_counts.items():
        merged[t] = merged.get(t, 0) + c

    results = sorted(
        [TrendingTopic(topic=t, count=c) for t, c in merged.items() if c > 0],
        key=lambda x: x.count, reverse=True
    )[:8]

    return results or [TrendingTopic(topic="Evidence-Based Medicine", count=0)]


@router.get("/stats", response_model=LandingStats)
def landing_stats(session: Session = Depends(get_session)):
    from sqlmodel import func as sfunc
    papers = session.exec(select(sfunc.count(Study.id))).one() or 0
    from backend.models import SynthesisResult
    synths = session.exec(select(sfunc.count(SynthesisResult.id))).one() or 0
    posts  = session.exec(
        select(sfunc.count(CommunityPost.id)).where(CommunityPost.is_deleted == False)
    ).one() or 0
    users  = session.exec(select(sfunc.count())).one() or 0
    return LandingStats(
        papers_analysed=papers,
        syntheses_run=synths,
        community_posts=posts,
        researchers=max(users, 0),
    )


@router.get("/recent-posts", response_model=List[CommunityPostRead])
def recent_posts(
    limit: int = 3,
    session: Session = Depends(get_session),
    username: Optional[str] = Depends(optional_user),
):
    posts = list(session.exec(
        select(CommunityPost)
        .where(CommunityPost.is_deleted == False)
        .order_by(CommunityPost.created_at.desc())
        .limit(limit)
    ).all())
    return [_enrich_post(p, session, username) for p in posts]


@router.get("/paper-of-day", response_model=Optional[PaperOfDay])
def paper_of_day(session: Session = Depends(get_session)):
    """Return a high-quality paper surfaced as 'paper of the day'."""
    from backend.models import AIResult
    # Look for papers with clinical AI results (evidence_strength >= 4)
    metrics = list(session.exec(
        select(StudyMetrics).where(StudyMetrics.evidence_strength >= 4)
    ).all())

    if not metrics:
        metrics = list(session.exec(select(StudyMetrics)).all())

    if not metrics:
        return None

    # Deterministic by day-of-year so everyone sees the same paper
    import datetime as dt
    day_idx = dt.date.today().timetuple().tm_yday % len(metrics)
    m = metrics[day_idx]

    study = session.get(Study, m.study_id)
    if not study:
        return None

    # Get AI summary if available
    from backend.models import AIResult
    ai = session.exec(
        select(AIResult).where(
            AIResult.cache_key.contains(str(m.study_id)),
            AIResult.kind == "summarize",
        )
    ).first()
    summary = (ai.summary or "")[:200] + "…" if ai and ai.summary else f"A {study.study_type or 'research'} study published in {study.year or 'recent years'}."

    return PaperOfDay(
        title=study.title,
        year=study.year,
        study_type=study.study_type,
        summary=summary,
        doi=study.doi,
        source=study.source,
    )


# ── Posts ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[CommunityPostRead])
def list_posts(
    q: Optional[str] = None,
    tag: Optional[str] = None,
    post_type: Optional[str] = None,
    sort: str = Query(default="latest", pattern="^(latest|replies|trending)$"),
    limit: int = Query(default=20, le=50),
    offset: int = 0,
    session: Session = Depends(get_session),
    username: Optional[str] = Depends(optional_user),
):
    stmt = select(CommunityPost).where(CommunityPost.is_deleted == False)

    if q:
        q_lower = q.lower()
        posts = [p for p in session.exec(stmt).all()
                 if q_lower in p.title.lower() or q_lower in p.body.lower()]
    else:
        posts = list(session.exec(stmt).all())

    if tag:
        posts = [p for p in posts if p.tags and tag in p.tags]
    if post_type:
        posts = [p for p in posts if p.post_type == post_type]

    if sort == "latest":
        posts.sort(key=lambda p: p.created_at, reverse=True)
    elif sort == "replies":
        posts.sort(key=lambda p: p.reply_count, reverse=True)
    elif sort == "trending":
        posts.sort(key=lambda p: (p.upvotes * 2 + p.reply_count), reverse=True)

    posts = posts[offset: offset + limit]
    return [_enrich_post(p, session, username) for p in posts]


@router.post("", response_model=CommunityPostRead, status_code=201)
def create_post(
    body: CommunityPostCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    if body.post_type not in ["question", "discussion", "case_study", "resource"]:
        raise HTTPException(400, "Invalid post_type")

    if body.study_id:
        study = session.get(Study, body.study_id)
        if not study:
            raise HTTPException(404, "Study not found")

    post = CommunityPost(
        author=username,
        is_anonymous=body.is_anonymous,
        title=body.title,
        body=body.body,
        post_type=body.post_type,
        tags=body.tags,
        study_id=body.study_id,
    )
    session.add(post)
    session.commit()
    session.refresh(post)
    return _enrich_post(post, session, username)


@router.get("/{post_id}", response_model=CommunityPostRead)
def get_post(
    post_id: int,
    session: Session = Depends(get_session),
    username: Optional[str] = Depends(optional_user),
):
    post = session.get(CommunityPost, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "Post not found")
    return _enrich_post(post, session, username)


@router.patch("/{post_id}", response_model=CommunityPostRead)
def update_post(
    post_id: int,
    body: CommunityPostPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    post = session.get(CommunityPost, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "Post not found")
    if post.author != username:
        raise HTTPException(403, "Not your post")

    if body.title is not None:
        post.title = body.title
    if body.body is not None:
        post.body = body.body
    if body.tags is not None:
        post.tags = body.tags

    post.updated_at = datetime.now(timezone.utc)
    session.add(post)
    session.commit()
    session.refresh(post)
    return _enrich_post(post, session, username)


@router.delete("/{post_id}", status_code=204)
def delete_post(
    post_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    post = session.get(CommunityPost, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "Post not found")
    if post.author != username:
        raise HTTPException(403, "Not your post")
    post.is_deleted = True
    session.add(post)
    session.commit()


@router.post("/{post_id}/upvote")
def toggle_post_upvote(
    post_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    post = session.get(CommunityPost, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "Post not found")

    existing = session.exec(
        select(CommunityUpvote).where(
            CommunityUpvote.username == username,
            CommunityUpvote.target_id == post_id,
            CommunityUpvote.target_type == "post",
        )
    ).first()

    if existing:
        session.delete(existing)
        post.upvotes = max(0, post.upvotes - 1)
        upvoted = False
    else:
        session.add(CommunityUpvote(username=username, target_id=post_id, target_type="post"))
        post.upvotes += 1
        upvoted = True

    session.add(post)
    session.commit()
    return {"upvoted": upvoted, "upvotes": post.upvotes}


# ── Replies ───────────────────────────────────────────────────────────────────

@router.get("/{post_id}/replies", response_model=List[CommunityReplyRead])
def get_replies(
    post_id: int,
    session: Session = Depends(get_session),
    username: Optional[str] = Depends(optional_user),
):
    post = session.get(CommunityPost, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "Post not found")

    replies = list(session.exec(
        select(CommunityReply)
        .where(CommunityReply.post_id == post_id, CommunityReply.is_deleted == False)
        .order_by(CommunityReply.created_at)
    ).all())

    return _build_reply_tree(replies, session, username)


@router.post("/{post_id}/replies", response_model=CommunityReplyRead, status_code=201)
def create_reply(
    post_id: int,
    body: CommunityReplyCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    post = session.get(CommunityPost, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "Post not found")

    if body.parent_reply_id:
        parent = session.get(CommunityReply, body.parent_reply_id)
        if not parent or parent.post_id != post_id:
            raise HTTPException(404, "Parent reply not found")

    reply = CommunityReply(
        post_id=post_id,
        parent_reply_id=body.parent_reply_id,
        author=username,
        is_anonymous=body.is_anonymous,
        body=body.body,
    )
    session.add(reply)
    post.reply_count += 1
    session.add(post)
    session.commit()
    session.refresh(reply)

    out = CommunityReplyRead.model_validate(reply)
    out.author = _author_display(reply)
    return out


@router.patch("/replies/{reply_id}", response_model=CommunityReplyRead)
def update_reply(
    reply_id: int,
    body: CommunityReplyPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    reply = session.get(CommunityReply, reply_id)
    if not reply or reply.is_deleted:
        raise HTTPException(404, "Reply not found")
    if reply.author != username:
        raise HTTPException(403, "Not your reply")

    reply.body = body.body
    reply.updated_at = datetime.now(timezone.utc)
    session.add(reply)
    session.commit()
    session.refresh(reply)

    out = CommunityReplyRead.model_validate(reply)
    out.author = _author_display(reply)
    return out


@router.delete("/replies/{reply_id}", status_code=204)
def delete_reply(
    reply_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    reply = session.get(CommunityReply, reply_id)
    if not reply or reply.is_deleted:
        raise HTTPException(404, "Reply not found")
    if reply.author != username:
        raise HTTPException(403, "Not your reply")

    reply.is_deleted = True
    session.add(reply)

    post = session.get(CommunityPost, reply.post_id)
    if post:
        post.reply_count = max(0, post.reply_count - 1)
        session.add(post)

    session.commit()


@router.post("/replies/{reply_id}/upvote")
def toggle_reply_upvote(
    reply_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    reply = session.get(CommunityReply, reply_id)
    if not reply or reply.is_deleted:
        raise HTTPException(404, "Reply not found")

    existing = session.exec(
        select(CommunityUpvote).where(
            CommunityUpvote.username == username,
            CommunityUpvote.target_id == reply_id,
            CommunityUpvote.target_type == "reply",
        )
    ).first()

    if existing:
        session.delete(existing)
        reply.upvotes = max(0, reply.upvotes - 1)
        upvoted = False
    else:
        session.add(CommunityUpvote(username=username, target_id=reply_id, target_type="reply"))
        reply.upvotes += 1
        upvoted = True

    session.add(reply)
    session.commit()
    return {"upvoted": upvoted, "upvotes": reply.upvotes}


# ── Bookmarks ─────────────────────────────────────────────────────────────────

@router.post("/bookmarks")
def toggle_bookmark(
    body: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    target_id   = body.get("target_id")
    target_type = body.get("target_type", "post")

    if not target_id or target_type not in ("post", "reply"):
        raise HTTPException(400, "Invalid bookmark target")

    existing = session.exec(
        select(Bookmark).where(
            Bookmark.owner_username == username,
            Bookmark.target_id == target_id,
            Bookmark.target_type == target_type,
        )
    ).first()

    if existing:
        session.delete(existing)
        session.commit()
        return {"bookmarked": False}

    bm = Bookmark(owner_username=username, target_id=target_id, target_type=target_type)
    session.add(bm)
    session.commit()
    return {"bookmarked": True}


@router.get("/bookmarks/me", response_model=List[BookmarkRead])
def list_bookmarks(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    username = current_user.username
    stmt = select(Bookmark).where(Bookmark.owner_username == username)
    return list(session.exec(stmt).all())