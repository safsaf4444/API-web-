# backend/services/study_analysis.py

import re
from typing import Optional


_STUDY_RULES = [
    ("Systematic Review", [r"\bsystematic review\b", r"\bmeta-analys(is|es)\b"]),
    ("Randomized Controlled Trial", [r"\brandomi[sz]ed\b", r"\bcontrolled trial\b", r"\bdouble[- ]blind\b"]),
    ("Cohort", [r"\bcohort\b", r"\bprospective\b", r"\bretrospective\b"]),
    ("Case-Control", [r"\bcase-control\b"]),
    ("Cross-Sectional", [r"\bcross-sectional\b"]),
    ("Case Report", [r"\bcase report\b", r"\bcase series\b"]),
    ("Guideline", [r"\bguideline\b", r"\bconsensus\b", r"\brecommendations\b"]),
    ("Protocol", [r"\bprotocol\b", r"\btrial registration\b"]),
]

_TAG_RULES = [
    ("covid-19", [r"\bcovid-19\b", r"\bsars-cov-2\b"]),
    ("pediatrics", [r"\bpediatric\b", r"\bchildren\b", r"\badolescent\b"]),
    ("elderly", [r"\belderly\b", r"\bolder adults\b", r"\bgeriatric\b"]),
    ("pregnancy", [r"\bpregnan(t|cy)\b", r"\bprenatal\b"]),
    ("mortality", [r"\bmortality\b", r"\bdeath\b"]),
    ("safety", [r"\badverse events?\b", r"\bsafety\b", r"\btoxicity\b"]),
]


def detect_study_type_and_tags(title: str, abstract: Optional[str]):
    text = f"{title}\n{abstract or ''}".lower()

    study_type = None
    for label, patterns in _STUDY_RULES:
        if any(re.search(p, text) for p in patterns):
            study_type = label
            break

    tags = []
    for tag, patterns in _TAG_RULES:
        if any(re.search(p, text) for p in patterns):
            tags.append(tag)

    return study_type, tags
