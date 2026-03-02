from __future__ import annotations

import html as html_lib
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend.ai_secure import decrypt_api_key, encrypt_api_key, mask_key
from backend.auth import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from backend.db import get_session, init_db
from backend.external_providers import ProviderError, get_provider, list_sources
from backend.models import Comment, Folder, Study, User
from backend.schemas import (
    AIAskRequest,
    AIAskResponse,
    AIKeySetRequest,
    AIKeyStatus,
    AISummarizeRequest,
    AISummarizeResponse,
    CommentCreate,
    CommentPatch,
    ExternalImportRequest,
    ExternalPaperOut,
    FullTextResponse,
    FolderCreate,
    FolderRead,
    LoginRequest,
    RegisterRequest,
    StudyPatch,
    StudyRead,
    TokenResponse,
    UserPublic,
)

app = FastAPI(title="Medical Evidence API")

# -----------------------------
# CORS (DEV)
# - Live Server runs on 127.0.0.1/localhost and can change ports.
# - allow_origin_regex makes it robust.
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # DEV: allow all
    allow_credentials=False,      # must be False when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def root():
    return {"status": "ok", "message": "Backend running"}


def normalize_source(src: str) -> str:
    return (src or "").strip().lower().replace(" ", "_").replace("-", "_")


# -----------------------------
# Auth dependency
# -----------------------------
def get_current_user(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    username = decode_token(parts[1])
    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# -----------------------------
# Study type + tags detector
# -----------------------------
_STUDY_RULES: list[tuple[str, list[str]]] = [
    ("Systematic Review", [r"\bsystematic review\b", r"\bmeta-analys(is|es)\b"]),
    ("Randomized Controlled Trial", [r"\brandomi[sz]ed\b", r"\bcontrolled trial\b", r"\bdouble[- ]blind\b"]),
    ("Cohort", [r"\bcohort\b", r"\bprospective\b", r"\bretrospective\b"]),
    ("Case-Control", [r"\bcase-control\b"]),
    ("Cross-Sectional", [r"\bcross-sectional\b"]),
    ("Case Report", [r"\bcase report\b", r"\bcase series\b"]),
    ("Guideline", [r"\bguideline\b", r"\bconsensus\b", r"\brecommendations\b"]),
    ("Protocol", [r"\bprotocol\b", r"\btrial registration\b"]),
]

_TAG_RULES: list[tuple[str, list[str]]] = [
    ("covid-19", [r"\bcovid-19\b", r"\bsars-cov-2\b"]),
    ("pediatrics", [r"\bpediatric\b", r"\bchildren\b", r"\badolescent\b"]),
    ("elderly", [r"\belderly\b", r"\bolder adults\b", r"\bgeriatric\b"]),
    ("pregnancy", [r"\bpregnan(t|cy)\b", r"\bprenatal\b"]),
    ("mortality", [r"\bmortality\b", r"\bdeath\b"]),
    ("safety", [r"\badverse events?\b", r"\bsafety\b", r"\btoxicity\b"]),
]


def detect_study_type_and_tags(title: str, abstract: Optional[str]) -> tuple[Optional[str], list[str]]:
    text = f"{title}\n{abstract or ''}".lower()
    study_type: Optional[str] = None

    for label, patterns in _STUDY_RULES:
        if any(re.search(p, text) for p in patterns):
            study_type = label
            break

    tags: list[str] = []
    for tag, patterns in _TAG_RULES:
        if any(re.search(p, text) for p in patterns):
            tags.append(tag)

    return study_type, tags


# -----------------------------
# OpenAI (BYOK)
# -----------------------------
def _get_openai_model() -> str:
    return (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


async def _call_openai(user_api_key: str, system: str, user: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {user_api_key}", "Content-Type": "application/json"}
    payload = {
        "model": _get_openai_model(),
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }

    async with httpx.AsyncClient(timeout=40.0) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="AI key rejected (401). Set a valid key in AI settings.")
    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="AI rate limit hit (429). Try again soon.")
    if r.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"AI error HTTP {r.status_code}: {r.text[:300]}")

    data = r.json()
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        raise HTTPException(status_code=500, detail="AI response parse error")


def _user_key_or_400(current_user: User) -> str:
    if not current_user.ai_key_enc:
        raise HTTPException(status_code=400, detail="No AI key set. Go to Info page and add your key.")
    try:
        return decrypt_api_key(current_user.ai_key_enc)
    except Exception:
        raise HTTPException(status_code=400, detail="Stored AI key cannot be decrypted. Clear and re-set your key.")


# -----------------------------
# Auth routes
# -----------------------------
@app.post("/auth/register", response_model=UserPublic)
def register(payload: RegisterRequest, session: Session = Depends(get_session)):
    existing = session.exec(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    user = User(
        username=payload.username.strip(),
        email=payload.email.strip().lower(),
        hashed_password=hash_password(payload.password),
    )

    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Username or email already exists")

    session.refresh(user)
    return UserPublic(id=user.id, username=user.username, email=user.email)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == payload.username)).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(subject=user.username)
    return TokenResponse(access_token=token)


@app.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)):
    return UserPublic(id=current_user.id, username=current_user.username, email=current_user.email)


@app.get("/auth/token_status")
def token_status(
    token: str | None = Query(default=None, description="Optional token if not using Authorization header"),
    authorization: str | None = Header(default=None),
):
    """
    Accepts token from either:
    - Authorization: Bearer <token>   (preferred)
    - ?token=<token>                  (fallback for frontend)
    """
    raw_token: str | None = None

    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1]

    if not raw_token and token:
        raw_token = token.strip()

    if not raw_token:
        raise HTTPException(status_code=401, detail="Missing token (Authorization header or ?token=)")

    try:
        payload = jwt.decode(raw_token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = payload.get("exp")
        sub = payload.get("sub")

        now = datetime.now(timezone.utc).timestamp()
        exp_ts = float(exp) if exp is not None else None
        seconds_left = int(exp_ts - now) if exp_ts else None

        return {"valid": True, "sub": sub, "exp": exp_ts, "seconds_left": seconds_left}
    except JWTError:
        return {"valid": False}


# -----------------------------
# AI Key routes (Protected)
# -----------------------------
@app.get("/ai/key_status", response_model=AIKeyStatus)
def ai_key_status(current_user: User = Depends(get_current_user)):
    if not current_user.ai_key_enc:
        return AIKeyStatus(has_key=False, masked=None)
    try:
        key = decrypt_api_key(current_user.ai_key_enc)
        return AIKeyStatus(has_key=True, masked=mask_key(key))
    except Exception:
        return AIKeyStatus(has_key=False, masked=None)


@app.post("/ai/set_key")
def ai_set_key(
    payload: AIKeySetRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    k = (payload.api_key or "").strip()
    if not k or len(k) < 20:
        raise HTTPException(status_code=400, detail="Invalid API key format.")
    current_user.ai_key_enc = encrypt_api_key(k)
    session.add(current_user)
    session.commit()
    return {"status": "ok"}


@app.delete("/ai/clear_key")
def ai_clear_key(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    current_user.ai_key_enc = None
    session.add(current_user)
    session.commit()
    return {"status": "cleared"}


# -----------------------------
# AI (no-save) routes (Protected)
# -----------------------------
@app.post("/ai/summarize", response_model=AISummarizeResponse)
async def ai_summarize(payload: AISummarizeRequest, current_user: User = Depends(get_current_user)):
    api_key = _user_key_or_400(current_user)

    system = (
        "You are a careful medical evidence assistant. "
        "Write in clear plain English. Use short headings and bullet points. "
        "Do not invent results. If info is missing, say so."
    )

    user_msg = (
        f"Summarize this paper.\n\n"
        f"Title: {payload.title}\n"
        f"Venue: {payload.venue or 'n/a'}\n"
        f"Year: {payload.year or 'n/a'}\n"
        f"PMID: {payload.pmid or 'n/a'}\n"
        f"PMCID: {payload.pmcid or 'n/a'}\n"
        f"DOI: {payload.doi or 'n/a'}\n\n"
        f"Abstract:\n{_strip_html(payload.abstract or '')}"
    )

    text = await _call_openai(api_key, system, user_msg)
    return AISummarizeResponse(text=text)


@app.post("/ai/ask", response_model=AIAskResponse)
async def ai_ask(payload: AIAskRequest, current_user: User = Depends(get_current_user)):
    api_key = _user_key_or_400(current_user)

    system = (
        "You are a medical evidence assistant. "
        "Answer the user's question using ONLY the provided title/abstract context. "
        "If the abstract doesn't contain the answer, say what is missing and what to look for. "
        "Use concise bullet points when helpful."
    )

    user_msg = (
        f"Question: {payload.question}\n\n"
        f"Paper:\n"
        f"Title: {payload.title}\n"
        f"Venue: {payload.venue or 'n/a'}\n"
        f"Year: {payload.year or 'n/a'}\n"
        f"PMID: {payload.pmid or 'n/a'}\n"
        f"PMCID: {payload.pmcid or 'n/a'}\n"
        f"DOI: {payload.doi or 'n/a'}\n\n"
        f"Abstract:\n{_strip_html(payload.abstract or '')}"
    )

    text = await _call_openai(api_key, system, user_msg)
    return AIAskResponse(text=text)


# -----------------------------
# Folders (Protected)
# -----------------------------
@app.get("/folders", response_model=List[FolderRead])
def list_folders(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    return session.exec(
        select(Folder).where(Folder.owner_username == current_user.username).order_by(Folder.name.asc())
    ).all()


@app.post("/folders", response_model=FolderRead)
def create_folder(payload: FolderCreate, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
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


@app.delete("/folders/{folder_id}")
def delete_folder(folder_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    f = session.get(Folder, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    if f.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    studies = session.exec(
        select(Study).where(Study.owner_username == current_user.username, Study.folder_id == folder_id)
    ).all()
    for s in studies:
        s.folder_id = None
        session.add(s)

    session.delete(f)
    session.commit()
    return {"status": "deleted", "folder_id": folder_id}


# -----------------------------
# Studies (Protected)
# -----------------------------
@app.get("/studies", response_model=List[StudyRead])
def list_studies(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    q: Optional[str] = Query(default=None, description="Search title + abstract"),
    sort: str = Query(default="newest", description="newest|oldest|year_desc|year_asc|title_asc|title_desc"),
    folder_id: Optional[int] = Query(default=None),
):
    stmt = select(Study).where(Study.owner_username == current_user.username)

    if folder_id is not None:
        stmt = stmt.where(Study.folder_id == folder_id)

    if q and q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Study.title.ilike(needle), Study.abstract.ilike(needle)))

    sort_key = (sort or "newest").strip().lower()
    if sort_key == "oldest":
        stmt = stmt.order_by(Study.id.asc())
    elif sort_key == "year_desc":
        stmt = stmt.order_by(Study.year.desc().nullslast(), Study.id.desc())
    elif sort_key == "year_asc":
        stmt = stmt.order_by(Study.year.asc().nullsfirst(), Study.id.desc())
    elif sort_key == "title_asc":
        stmt = stmt.order_by(Study.title.asc(), Study.id.desc())
    elif sort_key == "title_desc":
        stmt = stmt.order_by(Study.title.desc(), Study.id.desc())
    else:
        stmt = stmt.order_by(Study.id.desc())

    return session.exec(stmt).all()


@app.get("/studies/{study_id}", response_model=StudyRead)
def get_study(study_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")
    return study


@app.patch("/studies/{study_id}", response_model=StudyRead)
def patch_study(
    study_id: int,
    payload: StudyPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    fields_set = getattr(payload, "model_fields_set", set())

    if "notes" in fields_set:
        study.notes = payload.notes

    if "folder_id" in fields_set:
        if payload.folder_id is None:
            study.folder_id = None
        else:
            f = session.get(Folder, payload.folder_id)
            if not f or f.owner_username != current_user.username:
                raise HTTPException(status_code=400, detail="Invalid folder_id")
            study.folder_id = payload.folder_id

    session.add(study)
    session.commit()
    session.refresh(study)
    return study


@app.delete("/studies/{study_id}")
def delete_study(study_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    comments = session.exec(select(Comment).where(Comment.study_id == study_id)).all()
    for c in comments:
        session.delete(c)

    session.delete(study)
    session.commit()
    return {"status": "deleted", "study_id": study_id}


# -----------------------------
# Comments (Protected)
# -----------------------------
@app.get("/studies/{study_id}/comments")
def list_comments(study_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    return session.exec(select(Comment).where(Comment.study_id == study_id).order_by(Comment.id.asc())).all()


@app.post("/studies/{study_id}/comments")
def add_comment(study_id: int, payload: CommentCreate, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
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
        body=payload.body
    )
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


@app.patch("/comments/{comment_id}")
def edit_comment(comment_id: int, payload: CommentPatch, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    c = session.get(Comment, comment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Comment not found")

    # must own the study too
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


@app.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
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


# -----------------------------
# External (Public)
# -----------------------------
@app.get("/external/sources")
def external_sources():
    return {"sources": list_sources()}


@app.get("/external/search")
async def external_search(
    q: str = Query(..., min_length=2),
    source: str = Query("europepmc"),
    limit: int = Query(25, ge=1, le=100),
    cursor_mark: Optional[str] = Query(default=None),
):
    src = normalize_source(source)

    if cursor_mark is None or str(cursor_mark).strip() == "":
        cursor_mark = "0" if src in ("semantic_scholar", "semanticscholar") else "*"

    try:
        provider = get_provider(src)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        papers, next_cursor, hit_count = await provider.search(q=q, limit=limit, cursor_mark=str(cursor_mark))
    except ProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"External provider error: {type(e).__name__}: {e}")

    items = [
        ExternalPaperOut(
            source=p.source,
            source_id=p.source_id,
            title=p.title,
            year=p.year,
            authors=p.authors,
            venue=p.venue,
            doi=p.doi,
            url=p.url,
            abstract=p.abstract,
            pmid=p.pmid,
            pmcid=p.pmcid,
        )
        for p in papers
    ]
    return {"items": items, "next_cursor_mark": next_cursor, "hit_count": hit_count}


@app.post("/external/import", response_model=StudyRead)
def external_import(payload: ExternalImportRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    existing = session.exec(
        select(Study).where(
            (Study.owner_username == current_user.username)
            & (Study.source == payload.source)
            & (Study.source_id == payload.source_id)
        )
    ).first()
    if existing:
        return existing

    authors_str = None
    if payload.authors:
        authors_str = ", ".join([a for a in payload.authors if a])

    study_type, tags = detect_study_type_and_tags(payload.title or "", payload.abstract)
    tags_str = ", ".join(tags) if tags else None

    study = Study(
        owner_username=current_user.username,
        source=payload.source,
        source_id=payload.source_id,
        title=payload.title,
        year=payload.year,
        venue=payload.venue,
        abstract=payload.abstract,
        doi=payload.doi,
        url=payload.url,
        authors=authors_str,
        pmid=payload.pmid,
        pmcid=payload.pmcid,
        study_type=study_type,
        tags=tags_str,
    )
    session.add(study)
    session.commit()
    session.refresh(study)
    return study


# -----------------------------
# Fulltext OA (Public) - Europe PMC PMCID XML only
# -----------------------------
def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _xml_to_safe_html_paragraphs(xml_text: str, max_paragraphs: int = 250) -> str:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return ""

    paras: list[str] = []
    for el in root.iter():
        tag = el.tag
        if not isinstance(tag, str):
            continue
        if _strip_ns(tag).lower() != "p":
            continue

        txt = "".join(el.itertext()).strip()
        txt = re.sub(r"\s+", " ", txt)

        if len(txt) >= 40:
            paras.append(txt)
            if len(paras) >= max_paragraphs:
                break

    if not paras:
        return ""

    return "\n".join([f"<p>{html_lib.escape(p)}</p>" for p in paras])


@app.get("/external/fulltext", response_model=FullTextResponse)
async def external_fulltext(source: str = Query("europepmc"), pmcid: Optional[str] = Query(default=None)):
    src = normalize_source(source)
    if src not in ("europepmc", "europe_pmc"):
        return FullTextResponse(available=False, kind="not_available", message="Only europepmc supported (v1).")

    if not pmcid:
        return FullTextResponse(available=False, kind="not_available", message="No PMCID available for this record.")

    pmcid = pmcid.strip()
    if not pmcid.upper().startswith("PMC"):
        return FullTextResponse(available=False, kind="not_available", message="Invalid PMCID.")

    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"Accept": "application/xml"})

        if r.status_code == 404:
            return FullTextResponse(
                available=False,
                kind="not_available",
                message="No OA full text found for this PMCID on Europe PMC.",
            )

        if r.status_code != 200 or not r.text:
            return FullTextResponse(
                available=False,
                kind="not_available",
                message=f"Full text not available via Europe PMC (HTTP {r.status_code}).",
            )

        html = _xml_to_safe_html_paragraphs(r.text)
        if not html:
            return FullTextResponse(
                available=True,
                kind="pmc_xml",
                message="Full text XML exists, but no readable paragraphs were extracted.",
                html=None,
            )

        return FullTextResponse(
            available=True,
            kind="pmc_xml",
            message=f"Open-access full text loaded from Europe PMC ({pmcid}).",
            html=html,
        )

    except Exception as e:
        return FullTextResponse(available=False, kind="error", message=f"{type(e).__name__}: {e}")