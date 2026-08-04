"""
UAMD deep search map: faculties → departments → known official files.
Used to expand queries into a focused crawl of uamd.edu.al.
"""

from __future__ import annotations

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
        "files": [
            "https://uamd.edu.al/wp-content/uploads/2024/04/FSP.xlsx",
        ],
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
        "files": [
            "https://uamd.edu.al/wp-content/uploads/2024/04/FSHPJ.xlsx",
        ],
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
        "files": [
            "https://uamd.edu.al/wp-content/uploads/2024/04/FTI.xlsx",
        ],
    },
]


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


def deep_urls_for_question(question: str, limit: int = 12) -> list[dict[str, str]]:
    """
    Expand a user question into a deep set of official UAMD URLs.
    If a specific faculty is detected, crawl that faculty graph deeply.
    If asking generally about programs/faculties, include all faculty roots.
    """
    q = (question or "").lower()
    urls: list[dict[str, str]] = []

    matched = match_faculties(question)
    wants_programs = any(
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
        )
    )
    # Avoid treating "tarifat e studimit" / "viti i studimit" as a full program crawl
    if any(k in q for k in ("tarif", "pages", "pagesë", "pagesa", "kuota")) and not any(
        k in q for k in ("program", "programe", "bachelor", "master", "dega", "deget")
    ):
        wants_programs = False

    targets = matched
    if not targets and wants_programs:
        targets = FACULTIES[:]  # deep across all faculties
    if not targets and any(k in q for k in ("fakultet", "cilat fakultete", "sa fakultete")):
        targets = FACULTIES[:]

    for fac in targets:
        urls.append({"url": fac["url"], "title": fac["name"], "provider": "deep"})
        # For program questions, include all departments + files
        if wants_programs or matched:
            for dep in fac["departments"]:
                urls.append({"url": dep, "title": f"Departament — {fac['name']}", "provider": "deep"})
            for f in fac.get("files") or []:
                urls.append({"url": f, "title": f"Dokument — {fac['name']}", "provider": "deep"})

    # Always useful anchors
    if any(k in q for k in ("pranim", "aplik", "admission", "maturant")):
        urls.extend(
            [
                {"url": "https://admissions.prime-solutions.al/", "title": "Admissions UAMD", "provider": "deep"},
                {"url": "https://uamd.edu.al/kendi-i-maturantit/", "title": "Këndi i maturantit", "provider": "deep"},
            ]
        )

    # Deduplicate preserving order
    seen = set()
    out = []
    for item in urls:
        u = item["url"].rstrip("/") + ("/" if not item["url"].lower().endswith((".xlsx", ".xls", ".pdf")) else "")
        # normalize double slashes in path (except after https:)
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
