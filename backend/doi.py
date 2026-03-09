from __future__ import annotations

import re
from typing import Optional


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """
    Single canonical DOI normaliser for the entire project.
    Strips URL prefixes, whitespace, and returns None for empty/invalid.
    Import this everywhere instead of duplicating _clean_doi.
    """
    if not doi:
        return None
    d = str(doi).strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = d.strip()
    return d or None