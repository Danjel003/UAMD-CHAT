"""
UAMD deep search map: faculties → departments → known official files.
Used to expand queries into a focused crawl of uamd.edu.al.

Copyright (c) 2026 Danjel Kalari. All rights reserved.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Canonical faculty graph discovered from official UAMD pages.
FACULTIES: list[dict[str, Any]] = [
    {
        "id": "biznes",
        "name": "Fakulteti i Biznesit",
        "aliases": [
            "biznes",
            "fb",
            "fakulteti i biznesit",
            "ekonomi",
            "ekonomik",
            "marketing",
            "turizem",
            "turizëm",
            "menaxhim",
            "finance",
            "financë",
            "kontabilitet",
        ],
        "url": "https://uamd.edu.al/fakulteti-i-biznesit/",
        "departments": [
            "https://uamd.edu.al/departamenti-i-finances-dhe-kontabilitetit/",
            "https://uamd.edu.al/departamenti-i-marketingut/",
            "https://uamd.edu.al/departamenti-i-turizmit/",
            "https://uamd.edu.al/departamenti-i-menaxhimit/",
            "https://uamd.edu.al/departamenti-i-shkencave-ekonomike/",
            "https://uamd.edu.al/departamenti-i-statistikes-dhe-informatikes-se-zbatuar/",
        ],
        "files": [],
        "programs": [],
    },
    {
        "id": "edukim",
        "name": "Fakulteti i Edukimit",
        "aliases": [
            "edukim",
            "fe",
            "fakulteti i edukimit",
            "pedagogji",
            "psikologji",
            "sociologji",
            "gjuhe",
            "gjuhë",
            "letersi",
            "letërsi",
        ],
        "url": "https://uamd.edu.al/fakulteti-i-edukimit/",
        "departments": [
            "https://uamd.edu.al/departamenti-i-pedagogjise/",
            "https://uamd.edu.al/departamenti-i-gjuhes/",
            "https://uamd.edu.al/departamenti-i-letersise/",
            "https://uamd.edu.al/departamenti-i-gjuheve-te-huaja/",
            "https://uamd.edu.al/departamenti-i-sociologjise/",
            "https://uamd.edu.al/departamenti-i-psikologjise/",
        ],
        "files": [],
        "programs": [],
    },
    {
        "id": "profesionale",
        "name": "Fakulteti i Studimeve Profesionale",
        "aliases": [
            "profesionale",
            "fsp",
            "studimeve profesionale",
            "fakulteti i studimeve profesionale",
            "inxhinieri",
            "detare",
            "mjekesore",
            "mjekësore",
            "natyres",
            "natyrës",
        ],
        "url": "https://uamd.edu.al/fakulteti-i-studimeve-profesionale/",
        "departments": [
            "https://uamd.edu.al/departamenti-i-shkencave-teknike-mjekesore/",
            "https://uamd.edu.al/departamenti-i-shkencave-inxhinierike-dhe-detare/",
            "https://uamd.edu.al/departamenti-i-shkencave-te-aplikuara-dhe-te-natyres/",
            "https://uamd.edu.al/departamenti-i-studimeve-te-integruara-me-praktiken/",
        ],
        "files": [],
        "programs": [],
    },
    {
        "id": "juridike",
        "name": "Fakulteti i Shkencave Politike Juridike",
        "aliases": [
            "juridike",
            "fspj",
            "fshpj",
            "politike",
            "politike juridike",
            "drejtesi",
            "drejtësi",
            "ligj",
            "administrim publik",
            "shkenca politike",
        ],
        "url": "https://uamd.edu.al/fakulteti-i-shkencave-politike-juridike/",
        "departments": [
            "https://uamd.edu.al/departamenti-i-drejtesise/",
            "https://uamd.edu.al/departamenti-i-shkencave-politike/",
            "https://uamd.edu.al/departamenti-i-administrimit-publik/",
        ],
        "files": [],
        "programs": [],
    },
    {
        "id": "fti",
        "name": "Fakulteti i Teknologjisë së Informacionit",
        "aliases": [
            "fti",
            "teknologjis",
            "teknologji informacioni",
            "informatik",
            "kompjuterike",
            "softuer",
            "multimedia",
            "elektronik",
            "matematik",
        ],
        "url": "https://uamd.edu.al/fakulteti-i-teknologjise-se-informacionit/",
        "departments": [
            "https://uamd.edu.al/departamenti-i-teknologjise-se-informacionit/",
            "https://uamd.edu.al/departamenti-i-shkencave-kompjuterike/",
            "https://uamd.edu.al/departamenti-i-matematikes/",
        ],
        "files": [],
        # Optional fallback only (USE_CURATED_CATALOG=1). Prefer live faculty pages.
        "programs": [
            {"cycle": "Bachelor", "name": "Teknologji Informacioni", "dept": "Departamenti i Teknologjisë së Informacionit"},
            {"cycle": "Bachelor", "name": "Multimedia dhe Televizion Digjital", "dept": "Departamenti i Teknologjisë së Informacionit"},
            {"cycle": "Bachelor", "name": "Sisteme Informacioni", "dept": "Departamenti i Teknologjisë së Informacionit"},
            {"cycle": "Bachelor", "name": "Shkenca Kompjuterike", "dept": "Departamenti i Shkencave Kompjuterike"},
            {"cycle": "Bachelor", "name": "Informatikë Anglisht", "dept": "Departamenti i Shkencave Kompjuterike"},
            {"cycle": "Bachelor", "name": "Matematikë – Informatikë", "dept": "Departamenti i Matematikës"},
            {"cycle": "Master Shkencor", "name": "Quantum Information Technology", "dept": "Departamenti i Teknologjisë së Informacionit"},
            {"cycle": "Master Shkencor", "name": "Shkenca Kompjuterike të Aplikuara", "dept": "Departamenti i Shkencave Kompjuterike"},
            {"cycle": "Master Shkencor", "name": "Mësuesi në Matematikë – Informatikë", "dept": "Departamenti i Matematikës"},
            {"cycle": "Master Profesional", "name": "Multimedia dhe Televizion Digjital", "dept": "Departamenti i Teknologjisë së Informacionit"},
            {"cycle": "Master Profesional", "name": "Sisteme ERP", "dept": "Departamenti i Teknologjisë së Informacionit"},
            {"cycle": "Master Profesional", "name": "Shkenca Kompjuterike të Aplikuara", "dept": "Departamenti i Shkencave Kompjuterike"},
            {"cycle": "Program profesional 2-vjeçar", "name": "Specialist Pajisjesh Elektronike", "dept": "Departamenti i Teknologjisë së Informacionit"},
            {"cycle": "Program profesional 2-vjeçar", "name": "Aplikacione Web dhe Dizenjim Grafik", "dept": "Departamenti i Shkencave Kompjuterike"},
        ],
        "program_pages": [
            "https://uamd.edu.al/teknologji-informacioni/",
            "https://uamd.edu.al/shkenca-kompjuterike/",
            "https://uamd.edu.al/matematike-informatike/",
            "https://uamd.edu.al/english-study-programs/",
        ],
    },
]

ERASMUS_HUBS: list[dict[str, str]] = [
    {
        "url": "https://uamd.edu.al/marredheniet-me-jashte-dhe-projektet/",
        "title": "Marrëdhëniet me Jashtë dhe Projektet",
    },
]

STAFF_HUBS: list[dict[str, str]] = [
    {"url": "https://uamd.edu.al/rektorati/", "title": "Rektorati"},
    {"url": "https://uamd.edu.al/autoritetet-dhe-organet-drejtuese/", "title": "Autoritetet dhe organet drejtuese"},
    {"url": "https://uamd.edu.al/fjala-e-rektorit/", "title": "Fjala e Rektorit"},
    {
        "url": "https://uamd.edu.al/organika-e-personelit-akademik-ne-fakultetin-e-edukimit/",
        "title": "Organika — Fakulteti i Edukimit",
    },
    {
        "url": "https://uamd.edu.al/organika-e-personelit-akademik-ne-fakultetin-e-biznesit/",
        "title": "Organika — Fakulteti i Biznesit",
    },
]

_STOP_WORDS = {
    "cilat", "cili", "cfare", "çfarë", "jane", "janë", "eshte", "është", "esht",
    "mund", "duhet", "lutem", "juve", "kush", "kur", "ku", "sa", "nje", "një",
    "uamd", "universitet", "universiteti", "moisiu", "durres", "durrës",
    "lektor", "lektori", "lektorja", "pedagog", "pedagogu", "pedagoge",
    "profesor", "profesori", "profesoresha", "doktor", "doktoresha",
    "informacion", "info", "rreth", "per", "për", "me", "nga", "dhe", "ose",
    "te", "të", "ne", "në", "ma", "me", "jep", "trego", "thuaj", "a",
}


def extract_person_name(question: str) -> str:
    """Extract a likely person name from the question for deep staff search."""
    q = (question or "").strip()
    if not q:
        return ""

    patterns = [
        r"kush\s+(?:është|eshte|esht)\s+(.+?)[\?!.]*$",
        r"(?:lektor(?:i|ja|e)?|pedagog(?:u|e)?|profesor(?:i|e|esha)?|prof\.?|dr\.?|doc\.?)\s+(.+?)[\?!.]*$",
        r"(?:informacion|info|biografi|cv)\s+(?:për|per)\s+(.+?)[\?!.]*$",
        r"rreth\s+(.+?)[\?!.]*$",
    ]
    for pat in patterns:
        m = re.search(pat, q, flags=re.IGNORECASE)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" .?!,;:")
            # drop trailing filler
            name = re.sub(
                r"\b(ne|në|uamd|universitet(?:i)?|moisiu|durrës|durres)\b.*$",
                "",
                name,
                flags=re.IGNORECASE,
            ).strip(" .?!,;:")
            if len(name) >= 3:
                return name

    # Fallback: 2+ consecutive capitalized / name-like tokens
    tokens = re.findall(r"[A-ZÇËÁÉÍÓÚ][a-zçëáéíóúë]+(?:\s+[A-ZÇË][a-zçëáéíóúë]+)+", q)
    if tokens:
        return tokens[0].strip()

    # lowercase fallback: last 2 non-stop words (edi puka)
    words = [w for w in re.findall(r"[A-Za-zÇçËë]{2,}", q) if w.lower() not in _STOP_WORDS]
    if len(words) >= 2:
        return " ".join(words[-2:])
    if len(words) == 1 and len(words[0]) >= 4:
        return words[0]
    return ""


def wants_person_lookup(question: str) -> bool:
    q = (question or "").lower()
    if wants_program_list(question) and not any(
        k in q for k in ("lektor", "pedagog", "profesor", "kush është", "kush eshte")
    ):
        return False
    cues = [
        "kush është", "kush eshte", "kush esht",
        "lektor", "pedagog", "profesor", "prof.", "dr.", "doc.",
        "zv. rektor", "zëvendës rektor", "zv rektor", "dekan",
        "biografi", "organika", "stafi", "personeli akademik",
    ]
    if any(c in q for c in cues):
        return True
    # bare name-like query: 1-4 tokens, no university topic keywords
    name = extract_person_name(question)
    if not name:
        return False
    topic = any(
        k in q
        for k in (
            "program", "fakultet", "tarif", "orar", "erasmus", "pranim",
            "kalendar", "kontakt", "bibliotek", "kampus",
        )
    )
    return (not topic) and len(name.split()) <= 4


def match_faculties(question: str) -> list[dict[str, Any]]:
    q = (question or "").lower()
    hits = []
    for fac in FACULTIES:
        score = 0
        if fac["name"].lower() in q:
            score += 5
        for alias in fac["aliases"]:
            if alias in q:
                score += 2
        if score:
            hits.append((score, fac))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in hits]


def wants_program_list(question: str) -> bool:
    q = (question or "").lower()
    # "programet Erasmus / mobilitet" are NOT study-program catalog questions
    if wants_erasmus(question) and not any(
        k in q
        for k in (
            "fakultet",
            "bachelor",
            "bakalaure",
            "dega",
            "deget",
            "cikli i",
            "program studimi",
            "programe studimi",
            "programet e studimit",
        )
    ):
        return False
    if any(k in q for k in ("tarif", "pages", "pagesë", "pagesa", "kuota")) and not any(
        k in q for k in ("program", "programe", "bachelor", "master", "dega", "deget")
    ):
        return False
    return any(
        k in q
        for k in (
            "program",
            "programe",
            "bachelor",
            "master",
            "bakalaure",
            "cikel",
            "cikli",
            "dega",
            "deget",
            "sa programe",
            "cilat programe",
            "programet e studimit",
            "programe studimi",
            "program studimi",
            "profesionale",
        )
    )


def wants_erasmus(question: str) -> bool:
    q = (question or "").lower()
    return any(
        k in q
        for k in (
            "erasmus",
            "mobilitet",
            "mobiliteti",
            "shkëmbim",
            "shkembim",
            "ndërkombëtar",
            "nderkombetar",
            "marrëdhënieve me jashtë",
            "marredhenieve me jashte",
            "ka171",
            "ka1",
            "credit mobility",
        )
    )


def department_urls() -> list[dict[str, str]]:
    """All faculty department pages (used for person deep-dive phase 2)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for fac in FACULTIES:
        for dep in fac.get("departments") or []:
            if dep in seen:
                continue
            seen.add(dep)
            out.append({"url": dep, "title": f"Departament — {fac['name']}", "provider": "deep"})
    return out


def format_program_catalog(fac: dict[str, Any]) -> str:
    programs = fac.get("programs") or []
    if not programs:
        return ""
    lines = [f"Lista e plotë zyrtare e programeve — {fac['name']}:"]
    by_cycle: dict[str, list[str]] = {}
    for p in programs:
        by_cycle.setdefault(p["cycle"], []).append(p["name"])
    order = [
        "Bachelor",
        "Master Shkencor",
        "Master Profesional",
        "Program profesional 2-vjeçar",
    ]
    for cycle in order:
        names = by_cycle.get(cycle) or []
        if not names:
            continue
        lines.append(f"\n{cycle}:")
        for n in names:
            lines.append(f"- {n}")
    # any leftover cycles
    for cycle, names in by_cycle.items():
        if cycle in order:
            continue
        lines.append(f"\n{cycle}:")
        for n in names:
            lines.append(f"- {n}")
    lines.append(f"\nBurimi: {fac['url']}")
    for dep in fac.get("departments") or []:
        lines.append(f"Departament: {dep}")
    return "\n".join(lines)


def catalog_context_for_question(question: str) -> str:
    """Optional curated program lists — OFF by default so live pages win."""
    if os.getenv("USE_CURATED_CATALOG", "0").strip() != "1":
        return ""
    if not wants_program_list(question):
        return ""
    matched = match_faculties(question)
    targets = matched or ([] if "fakultet" not in question.lower() else FACULTIES[:])
    # If asking programs of a specific faculty, only that one
    blocks = []
    for fac in targets:
        block = format_program_catalog(fac)
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def deep_urls_for_question(question: str, limit: int = 12) -> list[dict[str, str]]:
    """
    Expand a user question into a deep set of official UAMD URLs.
    If a specific faculty is detected, crawl that faculty graph deeply.
    If asking generally about programs/faculties, include all faculty roots.
    """
    q = (question or "").lower()
    urls: list[dict[str, str]] = []

    matched = match_faculties(question)
    wants_programs = wants_program_list(question)

    targets = matched
    if not targets and wants_programs:
        targets = FACULTIES[:]  # deep across all faculties
    if not targets and any(k in q for k in ("fakultet", "cilat fakultete", "sa fakultete")):
        targets = FACULTIES[:]

    for fac in targets:
        urls.append({"url": fac["url"], "title": fac["name"], "provider": "deep"})
        # For program questions, include ALL departments + files + program pages
        if wants_programs or matched:
            for dep in fac["departments"]:
                urls.append({"url": dep, "title": f"Departament — {fac['name']}", "provider": "deep"})
            for f in fac.get("files") or []:
                urls.append({"url": f, "title": f"Dokument — {fac['name']}", "provider": "deep"})
            for p in fac.get("program_pages") or []:
                urls.append({"url": p, "title": f"Program — {fac['name']}", "provider": "deep"})

    if any(k in q for k in ("pranim", "aplik", "admission", "maturant")):
        urls.extend(
            [
                {"url": "https://admissions.prime-solutions.al/", "title": "Admissions UAMD", "provider": "deep"},
                {"url": "https://uamd.edu.al/kendi-i-maturantit/", "title": "Këndi i maturantit", "provider": "deep"},
            ]
        )

    if wants_erasmus(question):
        for hub in ERASMUS_HUBS:
            urls.append({"url": hub["url"], "title": hub["title"], "provider": "deep"})

    if wants_person_lookup(question):
        # Fast first: leadership/staff hubs only. Departments are fetched
        # in a second phase by rag_engine if the name is not found yet.
        for hub in STAFF_HUBS:
            urls.append({"url": hub["url"], "title": hub["title"], "provider": "deep"})


    # Deduplicate preserving order
    seen = set()
    out = []
    for item in urls:
        u = item["url"].rstrip("/") + ("/" if not item["url"].lower().endswith((".xlsx", ".xls", ".pdf")) else "")
        if "://" in u:
            scheme, rest = u.split("://", 1)
            while "//" in rest:
                rest = rest.replace("//", "/")
            u = scheme + "://" + rest
        if u in seen:
            continue
        seen.add(u)
        item = dict(item)
        item["url"] = u
        out.append(item)
        if len(out) >= limit:
            break
    return out
