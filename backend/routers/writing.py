from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import ast, json

from backend.db import get_session
from backend.models import User, SynthesisResult, Study
from backend.deps.auth import get_current_user
from backend.services.ai_engine import run as engine_run
from backend.routers.ai import _get_byok_keys, _build_synthesis_context

router = APIRouter(
    prefix="/ai/writing",
    tags=["Writing Support"]
)

class DraftRequest(BaseModel):
    section_name: str
    bullet_points: str
    synthesis_id: Optional[int] = None

@router.post("/draft-section")
async def draft_section(payload: DraftRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    ctx = ""
    if payload.synthesis_id:
        syn = session.get(SynthesisResult, payload.synthesis_id)
        if syn and syn.owner_username == user.username:
            try:
                studies = [session.get(Study, s) for s in json.loads(syn.study_ids or "[]") if isinstance(s, int) and session.get(Study, s)]
                ctx = _build_synthesis_context(studies, {})
            except: pass

    msg = f"Draft an academic section for '{payload.section_name}'.\n\nOutline bullet points:\n{payload.bullet_points}\n\nEvidence Context:\n{ctx}"
    result = await engine_run("You are a peer-reviewed academic co-author.", msg, **_get_byok_keys(user))
    return {"text": result.text}

class SynthesisRefRequest(BaseModel):
    synthesis_id: int

@router.post("/abstract")
async def write_abstract(payload: SynthesisRefRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    syn = session.get(SynthesisResult, payload.synthesis_id)
    if not syn or syn.owner_username != user.username: raise HTTPException(404)
    
    msg = f"Draft a structured abstract (Background, Methods, Results, Discussion, Conclusion) for this synthesis narrative.\n\nNarrative:\n{syn.synthesis_narrative}\n\nConclusion:\n{syn.weighted_conclusion}\n\nReturn EXACTLY a pure JSON object: {{'background':'','methods':'','results':'','discussion':'','conclusion':''}}"
    result = await engine_run("You are an academic author.", msg, **_get_byok_keys(user))
    try:
        return json.loads(result.text.replace('```json','').replace('```','').strip())
    except:
        return {"background": "Failed to parse JSON abstract", "methods":"", "results":"", "discussion":"", "conclusion":""}

class StudiesRefRequest(BaseModel):
    study_ids: List[int]

@router.post("/limitations")
async def write_limitations(payload: StudiesRefRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    studies = [session.get(Study, i) for i in payload.study_ids if session.get(Study, i) and session.get(Study, i).owner_username == user.username]
    ctx = "\\n".join([f"- {s.title}: {s.notes or ''}" for s in studies])
    msg = f"Draft a concise Limitations paragraph based on these studies:\n{ctx}"
    result = await engine_run("You are an academic author.", msg, **_get_byok_keys(user))
    return {"text": result.text}

@router.post("/future-work")
async def write_future_work(payload: SynthesisRefRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    syn = session.get(SynthesisResult, payload.synthesis_id)
    if not syn or syn.owner_username != user.username: raise HTTPException(404)
    msg = f"Draft a Future Work paragraph based on the gap analysis:\n{syn.gap_analysis}"
    result = await engine_run("You are an academic author.", msg, **_get_byok_keys(user))
    return {"text": result.text}

class DiscussionRequest(BaseModel):
    synthesis_id: int
    bullet_points: str

@router.post("/discussion")
async def write_discussion(payload: DiscussionRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    syn = session.get(SynthesisResult, payload.synthesis_id)
    if not syn or syn.owner_username != user.username: raise HTTPException(404)
    msg = f"Draft a Discussion section. Use these bullet points:\n{payload.bullet_points}\n\nReference this consensus:\n{syn.consensus_points}"
    result = await engine_run("You are an academic author.", msg, **_get_byok_keys(user))
    return {"text": result.text}

class ConferenceRequest(BaseModel):
    synthesis_id: int
    word_limit: int = 250

@router.post("/conference-abstract")
async def write_conference_abstract(payload: ConferenceRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    syn = session.get(SynthesisResult, payload.synthesis_id)
    if not syn or syn.owner_username != user.username: raise HTTPException(404)
    msg = f"Draft a {payload.word_limit}-word conference abstract for this conclusion: {syn.weighted_conclusion}\n\nNarrative: {syn.synthesis_narrative}"
    result = await engine_run("You are an academic author.", msg, **_get_byok_keys(user))
    return {"text": result.text}

class SingleStudyRequest(BaseModel):
    study_id: int

@router.post("/annotated-bibliography-entry")
async def annotated_bib_entry(payload: SingleStudyRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    s = session.get(Study, payload.study_id)
    if not s or s.owner_username != user.username: raise HTTPException(404)
    msg = f"Generate a 5-sentence structured annotation for this paper.\nAbstract: {s.abstract}"
    result = await engine_run("You are a concise academic extractor.", msg, **_get_byok_keys(user))
    return {"annotation": result.text}

@router.post("/annotated-bibliography")
async def annotated_bib_docx(payload: StudiesRefRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    from starlette.responses import StreamingResponse
    import io, docx
    
    doc = docx.Document()
    doc.add_heading('Annotated Bibliography', 0)
    
    for sid in payload.study_ids:
        s = session.get(Study, sid)
        if s and s.owner_username == user.username:
            doc.add_heading(f"{s.authors or 'Anon.'} ({s.year or 'n.d.'}). {s.title}.", level=2)
            doc.add_paragraph(s.ai_summary or "No summary available")
            
    mem = io.BytesIO()
    doc.save(mem)
    mem.seek(0)
    return StreamingResponse(mem, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": "attachment; filename=annotated_bibliography.docx"})

class CoverLetterRequest(BaseModel):
    synthesis_id: int
    journal_name: str

@router.post("/cover-letter")
async def write_cover_letter(payload: CoverLetterRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    syn = session.get(SynthesisResult, payload.synthesis_id)
    if not syn or syn.owner_username != user.username: raise HTTPException(404)
    msg = f"Draft a professional cover letter submitting a manuscript to {payload.journal_name}. Highlight this key conclusion: {syn.weighted_conclusion}"
    result = await engine_run("You are an academic author submitting a manuscript.", msg, **_get_byok_keys(user))
    return {"text": result.text}
