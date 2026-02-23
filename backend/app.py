from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok", "message": "Backend running"}
    from fastapi import FastAPI

app = FastAPI(title="Medical Evidence API")

@app.get("/")
def root():
    return {"status": "ok", "message": "Backend running"}

# Fake sample data for now (we’ll replace with a database later)
STUDIES = [
    {
        "id": 1,
        "title": "Example Study: Sleep and Memory",
        "year": 2022,
        "type": "Randomized Controlled Trial",
        "takeaway_plain": "Better sleep improved memory scores in students.",
        "limitations": ["Small sample size", "Short follow-up"],
    },
    {
        "id": 2,
        "title": "Example Study: Exercise and Depression",
        "year": 2020,
        "type": "Meta-analysis",
        "takeaway_plain": "Exercise was associated with fewer depressive symptoms.",
        "limitations": ["Study quality varied", "Different exercise programs"],
    },
]

@app.get("/studies")
def list_studies():
    return {"count": len(STUDIES), "results": STUDIES}

@app.get("/studies/{study_id}")
def get_study(study_id: int):
    for s in STUDIES:
        if s["id"] == study_id:
            return s
    return {"error": "Study not found", "study_id": study_id}