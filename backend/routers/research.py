from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List, Optional, Any
from pydantic import BaseModel
import ast, json, httpx

from backend.db import get_session
from backend.models import User, ResearchQuestion, Study
from backend.deps.auth import get_current_user
from backend.services.ai_engine import run as engine_run
from backend.routers.ai import _get_byok_keys

router = APIRouter(
    prefix="/research",
    tags=["Research Lifecycle"]
)

class QuestionCreate(BaseModel):
    question_text: str
    pico_json: Optional[Any] = None
    finer_scores_json: Optional[Any] = None

class QuestionPatch(BaseModel):
    question_text: Optional[str] = None
    pico_json: Optional[Any] = None
    finer_scores_json: Optional[Any] = None

@router.post("/question")
def create_question(payload: QuestionCreate, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    q = ResearchQuestion(
        owner_username=user.username,
        question_text=payload.question_text,
        pico_json=payload.pico_json,
        finer_scores_json=payload.finer_scores_json
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return q

@router.get("/questions")
def get_questions(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    stmt = select(ResearchQuestion).where(ResearchQuestion.owner_username == user.username).order_by(ResearchQuestion.id.desc())
    return session.exec(stmt).all()

@router.get("/question/{qid}")
def get_question(qid: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    q = session.get(ResearchQuestion, qid)
    if not q or q.owner_username != user.username: raise HTTPException(404)
    return q

@router.patch("/question/{qid}")
def patch_question(qid: int, payload: QuestionPatch, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    q = session.get(ResearchQuestion, qid)
    if not q or q.owner_username != user.username: raise HTTPException(404)
    
    if payload.question_text is not None: q.question_text = payload.question_text
    if payload.pico_json is not None: q.pico_json = payload.pico_json
    if payload.finer_scores_json is not None: q.finer_scores_json = payload.finer_scores_json
    
    session.add(q)
    session.commit()
    session.refresh(q)
    return q

@router.delete("/question/{qid}")
def delete_question(qid: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    q = session.get(ResearchQuestion, qid)
    if q and q.owner_username == user.username:
        session.delete(q)
        session.commit()
    return {"status": "ok"}

@router.post("/question/{qid}/generate-hypothesis")
async def generate_hypothesis(qid: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    q = session.get(ResearchQuestion, qid)
    if not q or q.owner_username != user.username: raise HTTPException(404)
    
    msg = f"Based on this research question: '{q.question_text}', generate a Null Hypothesis and an Alternative Hypothesis. Return valid JSON only strings format: {{'null_hypothesis': '...', 'alt_hypothesis': '...'}}"
    result = await engine_run("You are a scientific method expert.", msg, **_get_byok_keys(user))
    
    try:
        data = json.loads(result.text.replace('```json','').replace('```','').strip())
        q.hypothesis_null = data.get("null_hypothesis")
        q.hypothesis_alt = data.get("alt_hypothesis")
        session.add(q)
        session.commit()
        return {"null": q.hypothesis_null, "alt": q.hypothesis_alt}
    except Exception as e:
        raise HTTPException(502, "AI failed to format JSON response")

@router.post("/question/{qid}/generate-objectives")
async def generate_objectives(qid: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    q = session.get(ResearchQuestion, qid)
    if not q or q.owner_username != user.username: raise HTTPException(404)
    
    msg = f"Generate primary, secondary, and exploratory objectives for this research question: '{q.question_text}'. JSON format: {{'primary': '...', 'secondary': ['...'], 'exploratory': ['...']}}"
    result = await engine_run("You are a clinical trial protocol expert.", msg, **_get_byok_keys(user))
    
    try:
        data = json.loads(result.text.replace('```json','').replace('```','').strip())
        q.objectives_json = data
        session.add(q)
        session.commit()
        return data
    except Exception as e:
        raise HTTPException(502, "Error parsing AI response")

@router.post("/question/{qid}/novelty-check")
async def check_novelty(qid: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    q = session.get(ResearchQuestion, qid)
    if not q or q.owner_username != user.username: raise HTTPException(404)
    
    # 1. Fetch from Semantic Scholar
    import urllib.parse
    query_str = urllib.parse.quote(q.question_text)
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={query_str}&limit=5"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=10.0)
            data = resp.json()
            titles = [p.get("title") for p in data.get("data", [])]
        except:
            titles = []
            
    # 2. AI assessment
    msg = f"Question: '{q.question_text}'.\n\nThe following 5 highly relevant existing papers were found via Semantic Scholar:\n{json.dumps(titles)}\n\nAssess the novelty of this question relative to these existing papers. Give it a score from 1-10 (10 being completely novel). Return JSON: {{'score': int, 'notes': 'str'}}"
    
    result = await engine_run("You are an academic grant reviewer.", msg, **_get_byok_keys(user))
    try:
        ai_data = json.loads(result.text.replace('```json','').replace('```','').strip())
        q.novelty_score = ai_data.get("score")
        q.novelty_notes = ai_data.get("notes")
        session.add(q)
        session.commit()
        return {"score": q.novelty_score, "notes": q.novelty_notes}
    except Exception as e:
        raise HTTPException(502, "AI calculation failed")

@router.post("/library-gap-analysis")
async def library_gap_analysis(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    studies = session.exec(select(Study).where(Study.owner_username == user.username).limit(40)).all()
    if not studies:
        raise HTTPException(400, "No studies in library")
        
    ctx = "\\n".join([f"- {s.title} ({s.year})" for s in studies])
    msg = f"Based on the titles of my saved library, generate 5 structured research gaps that I could explore for a new paper.\n\nLibrary:\n{ctx}"
    
    result = await engine_run("You are an expert review analyst.", msg, **_get_byok_keys(user))
    return {"gaps_analysis": result.text}

@router.get("/question/{qid}/preregistration")
async def generate_preregistration(qid: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    from starlette.responses import StreamingResponse
    import io, docx
    
    q = session.get(ResearchQuestion, qid)
    if not q or q.owner_username != user.username: raise HTTPException(404)
    
    doc = docx.Document()
    doc.add_heading('Protocol & Pre-Registration Plan', 0)
    
    doc.add_heading('Research Question', level=1)
    doc.add_paragraph(q.question_text or "No question specified.")
    
    doc.add_heading('Hypotheses', level=1)
    doc.add_paragraph(f"Null: {q.hypothesis_null or 'TBD'}")
    doc.add_paragraph(f"Alternative: {q.hypothesis_alt or 'TBD'}")
    
    doc.add_heading('PICO Structure', level=1)
    doc.add_paragraph(json.dumps(q.pico_json) if q.pico_json else "None specified.")
    
    doc.add_heading('Objectives', level=1)
    doc.add_paragraph(json.dumps(q.objectives_json) if q.objectives_json else "None specified.")
    
    doc.add_heading('Novelty Assessment', level=1)
    doc.add_paragraph(f"Score: {q.novelty_score or 'N/A'}/10")
    doc.add_paragraph(q.novelty_notes or "")

    mem = io.BytesIO()
    doc.save(mem)
    mem.seek(0)
    
    return StreamingResponse(mem, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f"attachment; filename=protocol_q{qid}.docx"})

class EthicsChecklistRequest(BaseModel):
    study_type: str
    involves_humans: bool
    involves_nhs: bool
    collects_health_data: bool

@router.post("/ethics-checklist")
def ethics_checklist(payload: EthicsChecklistRequest):
    checklist = ["Data Protection Impact Assessment (DPIA) highly recommended."]
    if payload.involves_humans:
        checklist.append("Local Institutional Review Board (IRB) or University Ethics Approval required.")
        checklist.append("Informed consent forms required.")
    if payload.involves_nhs:
        checklist.append("HRA and REC (Research Ethics Committee) approval required in the UK via IRA.")
    if payload.collects_health_data:
        checklist.append("Ensure HIPAA (USA) or GDPR/Data Protection Act (UK/Europe) compliance for data transit and static storage.")
    return {"checklist": checklist}

class ReportingChecklistRequest(BaseModel):
    study_type: str

@router.post("/reporting-checklist")
def reporting_checklist(payload: ReportingChecklistRequest):
    guidelines = []
    st = payload.study_type.lower()
    if 'random' in st or 'rct' in st:
        guidelines = ["CONSORT - Title and abstract", "CONSORT - Background and objectives", "CONSORT - Trial design", "CONSORT - Randomisation", "CONSORT - Blinding"]
    elif 'review' in st or 'meta' in st:
        guidelines = ["PRISMA - Rationale", "PRISMA - Search Strategy", "PRISMA - Selection Process", "PRISMA - Risk of Bias", "PRISMA - Synthesis Methods"]
    elif 'cohort' in st or 'case-control' in st or 'cross-sec' in st:
        guidelines = ["STROBE - Setting", "STROBE - Participants", "STROBE - Variables", "STROBE - Statistical methods", "STROBE - Bias control"]
    else:
        guidelines = ["EQUATOR Network - Base items for observational reporting"]
    
    return [{"item": g, "where_in_paper": ""} for g in guidelines]
