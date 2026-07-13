# SEREN — Evidence & Research Exploration Network

A full-stack platform for searching, importing, and AI-appraising peer-reviewed medical research. Built solo by a Biomedical Science student at Royal Holloway, University of London.

**Live demo:** https://api-web-drab.vercel.app

---

## Contents

- [What it does](#what-it-does)
- [Features](#features)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Run locally](#run-locally)
- [Running tests](#running-tests)
- [Roadmap](#roadmap)
- [About](#about)

## What it does

Medical research is scattered across dozens of databases, inconsistently formatted, and difficult to evaluate quickly. This platform centralises search across four academic providers, removes duplicate results automatically, and uses AI to surface what matters in a paper — study design, key findings, and evidence quality.

## Features

| Feature | Detail |
| --- | --- |
| Multi-source search | Europe PMC, Semantic Scholar, OpenAlex, Crossref behind a unified provider abstraction layer |
| Deduplication engine | DOI-first matching with cross-source reference tracking and fuzzy-title fallback |
| Free-tier AI engine | Gemini Flash → Groq fallback, no API key required. BYOK OpenAI with encrypted key storage |
| Auth & security | JWT authentication, PBKDF2 password hashing, rate-limiting middleware |
| Test suite | 93 tests covering auth, deduplication, provider parsing, and study management — all passing |
| CI/CD | GitHub Actions runs lint and the full test suite on every push |
| Smart search filters | Automatic study-type detection — RCT, meta-analysis, cohort, systematic review |
| Paper detail | Structured abstract display, metadata badges, tabbed AI chat and comments panel |

## Tech stack

- **Backend:** Python · FastAPI · SQLModel · SQLite · Alembic · JWT · Fernet encryption
- **Testing & CI:** pytest · GitHub Actions · ruff
- **AI:** Gemini Flash · Groq (Llama 3.3) · OpenAI (BYOK)
- **Data sources:** Europe PMC · Semantic Scholar · OpenAlex · Crossref
- **Frontend:** Vanilla JavaScript · HTML · CSS

## Project structure

```
API-web-/
├── backend/
│   ├── app.py            # FastAPI application entry point
│   ├── auth.py           # Authentication logic
│   ├── models.py         # SQLModel database models
│   ├── schemas.py        # Pydantic request/response schemas
│   ├── core/             # Config, logging, errors, rate limiting
│   ├── routers/          # API routes (auth, studies, ai, external, comments…)
│   └── services/         # AI engine, dedup, metrics, email, analysis
├── frontend/             # Vanilla JS/HTML/CSS client
├── alembic/              # Database migrations
├── tests/                # pytest suite (auth, dedup, providers, studies)
├── .github/workflows/    # CI pipeline (ruff + pytest)
└── requirements.txt
```

## Run locally

```bash
# 1. Clone and create an environment
git clone https://github.com/safsaf4444/API-web-
cd API-web-
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the backend
$env:PYTHONPATH = "."            # Windows PowerShell
# export PYTHONPATH=.            # macOS/Linux
uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Then open `frontend/index.html` in your browser.

## Running tests

```bash
$env:PYTHONPATH = "."            # Windows PowerShell
# export PYTHONPATH=.            # macOS/Linux
pytest tests/ -v
```

## Roadmap

- Structured evidence extraction — PICO, NNT, bias-risk scoring
- Multi-paper synthesis — consensus and contradiction detection across studies
- Research translation — audience-specific summaries for patients, clinicians, and students
- Citation visualisation, semantic search, PDF upload and RAG pipeline

## About

Built by a second-year Biomedical Science student at Royal Holloway, University of London. Open to internships, placements, and work experience in digital health or software engineering.

**Contact:** safasaheerp@gmail.com · [github.com/safsaf4444](https://github.com/safsaf4444)
