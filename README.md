# Evidence & Research Exploration Network

A full-stack platform for searching, importing, and AI-analysing peer-reviewed medical research. Built as a solo project by a Biomedical Science student at Royal Holloway, University of London.

---

## What it does

Medical research is scattered across dozens of databases, inconsistently formatted, and difficult to evaluate quickly. This platform centralises search across four academic providers, removes duplicate results automatically, and uses AI to surface what matters in a paper — study design, key findings, and evidence quality.

---

## What's built

| Feature | Detail |
|---|---|
| **Multi-source search** | Europe PMC, Semantic Scholar, OpenAlex, Crossref behind a unified provider abstraction layer |
| **Deduplication engine** | DOI-first matching with cross-source reference tracking and fuzzy title fallback |
| **Free-tier AI engine** | Gemini Flash → Groq fallback, no API key required. BYOK OpenAI with encrypted key storage |
| **Auth & security** | JWT authentication, PBKDF2 password hashing, rate limiting middleware |
| **Test suite** | 93 tests covering auth, deduplication, provider parsing, and study management — all passing |
| **CI/CD** | GitHub Actions runs lint and full test suite on every push |
| **Smart search filters** | Automatic study type detection — RCT, meta-analysis, cohort, systematic review |
| **Paper detail** | Structured abstract display, metadata badges, tabbed AI chat and comments panel |

---

## Stack

**Backend:** Python · FastAPI · SQLModel · SQLite · Alembic · JWT · Fernet encryption

**Testing & CI:** pytest · GitHub Actions · ruff

**AI:** Gemini Flash · Groq (Llama 3.3) · OpenAI (BYOK)

**APIs:** Europe PMC · Semantic Scholar · OpenAlex · Crossref

**Frontend:** Vanilla JavaScript · HTML · CSS

---

## Running locally

```bash
# 1. Clone and activate environment
git clone https://github.com/safsaf4444/API-web-
cd API-web-
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the backend
$env:PYTHONPATH = "."
uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Open `frontend/index.html` in your browser.

---

## Running tests

```bash
$env:PYTHONPATH = "."
pytest tests/ -v
```

---

## In development

- Structured evidence extraction — PICO, NNT, bias risk scoring
- Multi-paper synthesis — consensus and contradiction detection across studies
- Research translation — audience-specific summaries for patients, clinicians, students
- Citation visualisation, semantic search, PDF upload and RAG pipeline

---

## About

Built by a second-year Biomedical Science student at Royal Holloway, University of London. Immediately available for internships, placements, and work experience in digital health or software engineering.

**Contact:** safasaheerp@gmail.com · [github.com/safsaf4444](https://github.com/safsaf4444)
