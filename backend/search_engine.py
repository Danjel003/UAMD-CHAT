"""
UAMD GPT — Restricted web search for site:uamd.edu.al
Providers: intent seeds → Tavily → SerpAPI → site crawl → DuckDuckGo.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from scraper import is_allowed_url, normalize_url
from uamd_map import deep_urls_for_question

load_dotenv()

SITE_FILTER = "site:uamd.edu.al"
MAX_RESULTS = 8
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SEED_URLS = [
    "https://uamd.edu.al/",
    "https://uamd.edu.al/faqja-kryesore/",
    "https://uamd.edu.al/misioni-dhe-vizioni/",
]

# Always merged into every search so random questions still get official context
ALWAYS_HUBS: list[dict[str, str]] = [
    {"url": "https://uamd.edu.al/", "title": "UAMD — Faqja zyrtare"},
    {"url": "https://uamd.edu.al/kendi-i-maturantit/", "title": "Këndi i maturantit"},
    {"url": "https://uamd.edu.al/kalendari-akademik/", "title": "Kalendari Akademik"},
    {"url": "https://uamd.edu.al/sekretarite-mesimore/", "title": "Sekretaritë Mësimore"},
    {"url": "https://uamd.edu.al/rektorati/", "title": "Rektorati"},
    {"url": "https://uamd.edu.al/biblioteka-universitare/", "title": "Biblioteka Universitare"},
    {"url": "https://uamd.edu.al/kontakto/", "title": "Kontakto"},
    {"url": "https://admissions.prime-solutions.al/", "title": "Admissions UAMD"},
]

# Curated official pages for common intents (accuracy boost)
INTENT_SEEDS: list[tuple[list[str], list[dict[str, str]]]] = [
    (
        ["fti", "teknologjis", "teknologji informacioni", "informatik", "softuer", "program studimi", "programe studimi", "cikli", "bachelor", "master"],
        [
            {"url": "https://uamd.edu.al/fakulteti-i-teknologjise-se-informacionit/", "title": "Fakulteti i Teknologjisë së Informacionit (FTI)"},
            {"url": "https://uamd.edu.al/departamenti-i-teknologjise-se-informacionit/", "title": "Departamenti i Teknologjisë së Informacionit"},
            {"url": "https://uamd.edu.al/departamenti-i-shkencave-kompjuterike/", "title": "Departamenti i Shkencave Kompjuterike"},
            {"url": "https://uamd.edu.al/fakulteti-i-biznesit/", "title": "Fakulteti i Biznesit"},
            {"url": "https://uamd.edu.al/fakulteti-i-edukimit/", "title": "Fakulteti i Edukimit"},
        ],
    ),
    (
        ["fakultet", "fakulteti", "fakultetet", "dega", "deget"],
        [
            {"url": "https://uamd.edu.al/fakulteti-i-biznesit/", "title": "Fakulteti i Biznesit"},
            {"url": "https://uamd.edu.al/fakulteti-i-edukimit/", "title": "Fakulteti i Edukimit"},
            {"url": "https://uamd.edu.al/fakulteti-i-studimeve-profesionale/", "title": "Fakulteti i Studimeve Profesionale"},
            {"url": "https://uamd.edu.al/fakulteti-i-shkencave-politike-juridike/", "title": "Fakulteti i Shkencave Politike Juridike"},
            {"url": "https://uamd.edu.al/fakulteti-i-teknologjise-se-informacionit/", "title": "Fakulteti i Teknologjisë së Informacionit"},
        ],
    ),
    (
        ["pranim", "pranime", "aplikim", "aplikoj", "admission", "maturant", "regjistr"],
        [
            {"url": "https://uamd.edu.al/", "title": "UAMD — Faqja zyrtare"},
            {"url": "https://uamd.edu.al/kendi-i-maturantit/", "title": "Këndi i maturantit"},
            {"url": "https://admissions.prime-solutions.al/", "title": "Admissions UAMD (portal zyrtar)"},
            {"url": "https://uamd.edu.al/sekretarite-mesimore/", "title": "Sekretaritë Mësimore"},
        ],
    ),
    (
        ["kontakt", "kontakto", "email", "telefon", "adres", "ndodhet", "ku eshte", "ku është", "lokacion", "location"],
        [
            {"url": "https://uamd.edu.al/", "title": "UAMD — Faqja zyrtare"},
            {"url": "https://uamd.edu.al/kontakto/", "title": "Kontakto"},
            {"url": "https://uamd.edu.al/faqja-kryesore/", "title": "Rreth Nesh"},
            {"url": "https://uamd.edu.al/sekretarite-mesimore/", "title": "Sekretaritë Mësimore"},
        ],
    ),
    (
        ["orar", "orari", "kalendar", "semest", "vit akademik", "viti akademik", "sekretari"],
        [
            {"url": "https://uamd.edu.al/orari-2/", "title": "Orari"},
            {"url": "https://uamd.edu.al/kalendari-akademik/", "title": "Kalendari Akademik"},
            {"url": "https://uamd.edu.al/sekretarite-mesimore/", "title": "Sekretaritë Mësimore"},
        ],
    ),
    (
        ["rektor", "administrat", "rektorat", "mision", "vizion", "rreth", "senat", "senati"],
        [
            {"url": "https://uamd.edu.al/rektorati/", "title": "Rektorati"},
            {"url": "https://uamd.edu.al/fjala-e-rektorit/", "title": "Fjala e Rektorit"},
            {"url": "https://uamd.edu.al/autoritetet-dhe-organet-drejtuese/", "title": "Autoritetet dhe organet drejtuese"},
            {"url": "https://uamd.edu.al/misioni-dhe-vizioni/", "title": "Misioni dhe Vizioni"},
            {"url": "https://uamd.edu.al/faqja-kryesore/", "title": "Rreth Nesh"},
        ],
    ),
    (
        ["tarif", "pages", "pagesë", "tarife", "çmim", "cmim", "kuota", "pagesa"],
        [
            {"url": "https://uamd.edu.al/kendi-i-maturantit/", "title": "Këndi i maturantit"},
            {"url": "https://admissions.prime-solutions.al/", "title": "Admissions UAMD"},
            {"url": "https://uamd.edu.al/sekretarite-mesimore/", "title": "Sekretaritë Mësimore"},
            {"url": "https://uamd.edu.al/", "title": "UAMD — Faqja zyrtare"},
        ],
    ),
    (
        ["pitagora", "kampus", "campus", "godin", "ndërtes", "ndertes"],
        [
            {"url": "https://uamd.edu.al/kampusi/", "title": "Kampusi"},
            {"url": "https://uamd.edu.al/pitagora/", "title": "Pitagora"},
            {"url": "https://uamd.edu.al/", "title": "UAMD — Faqja zyrtare"},
            {"url": "https://uamd.edu.al/faqja-kryesore/", "title": "Rreth Nesh"},
            {"url": "https://uamd.edu.al/kontakto/", "title": "Kontakto"},
        ],
    ),
    (
        ["lektor", "pedagog", "profesor", "organika", "stafi", "personeli", "zv. rektor", "zëvendës"],
        [
            {"url": "https://uamd.edu.al/rektorati/", "title": "Rektorati"},
            {"url": "https://uamd.edu.al/autoritetet-dhe-organet-drejtuese/", "title": "Autoritetet dhe organet drejtuese"},
            {
                "url": "https://uamd.edu.al/organika-e-personelit-akademik-ne-fakultetin-e-edukimit/",
                "title": "Organika — Fakulteti i Edukimit",
            },
            {
                "url": "https://uamd.edu.al/organika-e-personelit-akademik-ne-fakultetin-e-biznesit/",
                "title": "Organika — Fakulteti i Biznesit",
            },
        ],
    ),
    (
        ["erasmus", "mobilitet", "mobiliteti", "shkëmbim", "shkembim", "nderkombetar", "ndërkombëtar", "ka171"],
        [
            {"url": "https://uamd.edu.al/marredheniet-me-jashte-dhe-projektet/", "title": "Marrëdhëniet me Jashtë dhe Projektet"},
            {"url": "https://uamd.edu.al/", "title": "UAMD — Faqja zyrtare"},
            {"url": "https://uamd.edu.al/keshilli-studentor/", "title": "Këshilli studentor"},
        ],
    ),
    (
        ["student", "burs", "bibliotek", "alumni", "karrier"],
        [
            {"url": "https://uamd.edu.al/keshilli-studentor/", "title": "Këshilli studentor"},
            {"url": "https://uamd.edu.al/biblioteka-universitare/", "title": "Biblioteka Universitare"},
            {"url": "https://uamd.edu.al/bursa/", "title": "Bursa"},
            {"url": "https://uamd.edu.al/karriera/", "title": "Karriera"},
        ],
    ),
    (
        ["master", "bachelor", "bakalaureat", "doktoratur", "program"],
        [
            {"url": "https://uamd.edu.al/", "title": "UAMD — Faqja zyrtare"},
            {"url": "https://uamd.edu.al/fakulteti-i-biznesit/", "title": "Fakulteti i Biznesit"},
            {"url": "https://uamd.edu.al/fakulteti-i-edukimit/", "title": "Fakulteti i Edukimit"},
            {"url": "https://uamd.edu.al/fakulteti-i-teknologjise-se-informacionit/", "title": "Fakulteti i Teknologjisë së Informacionit"},
            {"url": "https://admissions.prime-solutions.al/", "title": "Admissions UAMD"},
        ],
    ),
]

_home_cache: dict[str, Any] = {"ts": 0.0, "candidates": []}
_home_lock = threading.Lock()
HOME_CACHE_TTL = int(os.getenv("HOME_CACHE_TTL", "300"))


def _as_hit(url: str, title: str = "", snippet: str = "", provider: str = "seed") -> dict[str, Any]:
    return {
        "url": normalize_url(url) if url.startswith("http") else url,
        "title": title,
        "snippet": snippet,
        "provider": provider,
    }


def _dedupe(results: list[dict[str, Any]], limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in results:
        url = item.get("url") or ""
        if url.startswith("http"):
            url = normalize_url(url)
        if not url or not is_allowed_url(url) or url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "url": url,
                "title": (item.get("title") or "").strip(),
                "snippet": (item.get("snippet") or "").strip(),
                "provider": item.get("provider", "unknown"),
            }
        )
        if len(out) >= limit:
            break
    return out


def intent_seed_search(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    q = query.lower()
    scored: list[tuple[int, list[dict[str, str]]]] = []
    for keywords, pages in INTENT_SEEDS:
        hits_n = sum(1 for k in keywords if k in q)
        if hits_n:
            scored.append((hits_n, pages))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits: list[dict[str, Any]] = []
    for _, pages in scored:
        for p in pages:
            hits.append(_as_hit(p["url"], p.get("title", ""), provider="intent"))
    return _dedupe(hits, max_results)


def search_tavily(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key or api_key.startswith("tvly-your"):
        return []
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=f"{query} {SITE_FILTER}",
            search_depth="basic",
            include_domains=["uamd.edu.al", "www.uamd.edu.al", "admissions.prime-solutions.al"],
            max_results=max_results,
        )
        results = []
        for r in response.get("results") or []:
            results.append(
                {
                    "url": r.get("url"),
                    "title": r.get("title"),
                    "snippet": r.get("content") or "",
                    "provider": "tavily",
                }
            )
        return _dedupe(results, max_results)
    except Exception as exc:
        print(f"[search] Tavily error: {exc}")
        return []


def search_serpapi(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key or api_key.startswith("your-"):
        return []
    try:
        params = {
            "engine": "google",
            "q": f"{query} {SITE_FILTER}",
            "api_key": api_key,
            "num": max_results,
            "hl": "sq",
        }
        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("organic_results") or []:
            results.append(
                {
                    "url": r.get("link"),
                    "title": r.get("title"),
                    "snippet": r.get("snippet") or "",
                    "provider": "serpapi",
                }
            )
        return _dedupe(results, max_results)
    except Exception as exc:
        print(f"[search] SerpAPI error: {exc}")
        return []


def _unwrap_ddg_redirect(href: str) -> str:
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])
    if href.startswith("//"):
        href = "https:" + href
    return href


def search_duckduckgo(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    try:
        q = quote_plus(f"{query} {SITE_FILTER}")
        url = f"https://html.duckduckgo.com/html/?q={q}"
        resp = requests.get(
            url,
            timeout=8,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if resp.status_code >= 400 or "result__a" not in resp.text:
            resp = requests.get(
                f"https://lite.duckduckgo.com/lite/?q={q}",
                timeout=8,
                headers={"User-Agent": USER_AGENT},
            )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results: list[dict[str, Any]] = []
        for result in soup.select(".result"):
            a = result.select_one("a.result__a")
            if not a or not a.get("href"):
                continue
            link = _unwrap_ddg_redirect(a["href"])
            snippet_el = result.select_one(".result__snippet")
            results.append(
                {
                    "url": link,
                    "title": a.get_text(" ", strip=True),
                    "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else "",
                    "provider": "duckduckgo",
                }
            )
        if not results:
            for a in soup.select("a.result-link"):
                href = a.get("href")
                if not href:
                    continue
                results.append(
                    {
                        "url": _unwrap_ddg_redirect(href),
                        "title": a.get_text(" ", strip=True),
                        "snippet": "",
                        "provider": "duckduckgo",
                    }
                )
        return _dedupe(results, max_results)
    except Exception as exc:
        print(f"[search] DuckDuckGo error: {exc}")
        return []


def _freshness_score(url: str) -> int:
    """Prefer current academic-year pages; demote old upload paths."""
    u = (url or "").lower()
    score = 0
    if "2026" in u:
        score += 40
    if "2025" in u:
        score += 30
    if "2024" in u:
        score += 5
    if "2023" in u or "2022" in u:
        score -= 15
    if "/wp-content/uploads/" in u and ("2024" in u or "2023" in u):
        score -= 25
    return score


def _is_newsish(url: str, title: str = "") -> bool:
    hay = f"{url} {title}".lower()
    return any(
        k in hay
        for k in (
            "priti",
            "takim",
            "vizitoi",
            "priti-nje",
            "priti-sot",
            "bashkepunues",
            "delegacion",
            "ambasadore",
        )
    )


def _prefer_fresh(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    ranked = sorted(
        results,
        key=lambda item: (
            0 if _is_newsish(item.get("url") or "", item.get("title") or "") else 2,
            _freshness_score(item.get("url") or ""),
            1 if (item.get("provider") or "").startswith("wp") else 0,
            3 if (item.get("provider") or "") == "canonical" else 0,
        ),
        reverse=True,
    )
    return _dedupe(ranked, limit)


def wp_site_search(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """Use the university WordPress search endpoint (+ REST API), newest first."""
    results: list[dict[str, Any]] = []
    # Keep short name tokens (Edi, Ana, …) — critical for lecturer lookup
    tokens = [
        t
        for t in re.findall(r"[a-zçëA-ZÇË]{2,}", query.lower())
        if t
        not in {
            "cilat", "cili", "cfare", "çfarë", "jane", "janë", "eshte", "është",
            "mund", "duhet", "lutem", "juve", "kush", "kur", "ku", "sa", "nje", "një",
            "uamd", "universitet", "universiteti", "moisiu", "durres", "durrës",
            "lektor", "lektori", "pedagog", "pedagogu", "profesor", "profesori",
            "informacion", "info", "rreth", "biografi",
        }
    ]
    search_q = " ".join(tokens[:6]) if tokens else query.strip()
    headers = {
        "User-Agent": USER_AGENT,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    def _append_rest_row(row: dict[str, Any], provider: str) -> None:
        href = row.get("url") or row.get("link")
        if not href:
            return
        title = row.get("title") or ""
        if isinstance(title, dict):
            title = title.get("rendered") or ""
        results.append(
            {
                "url": href,
                "title": BeautifulSoup(str(title), "lxml").get_text(" ", strip=True),
                "snippet": "",
                "provider": provider,
            }
        )

    try:
        api = (
            f"https://uamd.edu.al/wp-json/wp/v2/search?"
            f"search={quote_plus(search_q)}&per_page={max_results}"
        )
        resp = requests.get(api, timeout=6, headers=headers)
        if resp.status_code < 400:
            for row in resp.json() or []:
                _append_rest_row(row, "wp_rest")
    except Exception as exc:
        print(f"[search] WP REST error: {exc}")

    # Prefer recently modified pages/posts for freshness
    for endpoint, provider in (
        ("posts", "wp_posts"),
        ("pages", "wp_pages"),
    ):
        try:
            order_by = "date" if endpoint == "posts" else "modified"
            api = (
                f"https://uamd.edu.al/wp-json/wp/v2/{endpoint}?"
                f"search={quote_plus(search_q)}&per_page={max_results}"
                f"&orderby={order_by}&order=desc"
            )
            resp = requests.get(api, timeout=6, headers=headers)
            if resp.status_code < 400:
                for row in resp.json() or []:
                    _append_rest_row(row, provider)
        except Exception as exc:
            print(f"[search] WP {endpoint} error: {exc}")

    if results:
        return _prefer_fresh(results, max_results)

    try:
        url = f"https://uamd.edu.al/?s={quote_plus(search_q)}"
        resp = requests.get(url, timeout=5, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select(
            "article h2 a, h2.entry-title a, .search-results a, "
            ".gdlr-core-blog-title a, .kingster-blog-title a, h3 a"
        ):
            href = a.get("href")
            if not href:
                continue
            results.append(
                {
                    "url": href,
                    "title": a.get_text(" ", strip=True),
                    "snippet": "",
                    "provider": "wp_search",
                }
            )
    except Exception as exc:
        print(f"[search] WP search error: {exc}")

    return _prefer_fresh(results, max_results)


def _load_home_candidates() -> list[dict[str, Any]]:
    with _home_lock:
        if _home_cache["candidates"] and time.time() - _home_cache["ts"] < HOME_CACHE_TTL:
            return list(_home_cache["candidates"])

    home = "https://uamd.edu.al/"
    resp = requests.get(home, timeout=12, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    candidates = [
        _as_hit(home, "Universiteti Aleksandër Moisiu Durrës", provider="crawl")
    ]
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full = href if href.startswith("http") else urljoin(home, href)
        if not is_allowed_url(full):
            continue
        title = a.get_text(" ", strip=True)
        candidates.append(_as_hit(full, title or full, provider="crawl"))

    with _home_lock:
        _home_cache["ts"] = time.time()
        _home_cache["candidates"] = candidates
    return candidates


def crawl_uamd_site(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    tokens = [
        t
        for t in re.findall(r"[a-zçë0-9]{3,}", query.lower())
        if t
        not in {
            "the", "and", "per", "nga", "uamd", "edu", "www", "http", "https",
            "cilat", "cili", "cfare", "çfarë", "ka", "jane", "janë", "mund", "te",
        }
    ]
    try:
        candidates = _load_home_candidates()
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in candidates:
            path = urlparse(item["url"]).path.lower()
            hay = f"{item['title']} {path}".lower()
            score = sum(1 for t in tokens if t in hay)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = [item for _, item in scored] if scored else candidates
        return _dedupe(ranked, max_results)
    except Exception as exc:
        print(f"[search] Crawl error: {exc}")
        return _dedupe([_as_hit(u, "UAMD", provider="seed") for u in SEED_URLS], max_results)


def search_uamd(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """
    Hybrid search on uamd.edu.al.
    Always queries live WordPress first so answers prefer current official pages.
    """
    from uamd_map import (
        extract_person_name,
        wants_erasmus,
        wants_person_lookup,
        wants_program_list,
    )

    query = (query or "").strip()
    if not query:
        return []

    person = wants_person_lookup(query)
    person_name = extract_person_name(query) if person else ""
    wide = wants_program_list(query) or wants_erasmus(query) or person
    q_low = query.lower()
    is_rektor = any(k in q_low for k in ("rektor", "rektorat", "zv. rektor", "zëvendës rektor"))
    # Keep URL sets tight for speed; person deep-dive happens in rag phase-2
    limit = 10 if person else (12 if wide else min(max(max_results, 8), 8))
    specific: list[dict[str, Any]] = []
    # Avoid stuffing generic hubs into precise leadership/person answers
    if person or is_rektor:
        fallback = [
            _as_hit("https://uamd.edu.al/rektorati/", "Rektorati", provider="hub"),
            _as_hit(
                "https://uamd.edu.al/autoritetet-dhe-organet-drejtuese/",
                "Autoritetet",
                provider="hub",
            ),
        ]
    elif wants_program_list(query):
        fallback = []
    else:
        fallback = [_as_hit(h["url"], h["title"], provider="hub") for h in ALWAYS_HUBS[:3]]

    # Canonical leadership page first for rector questions
    if is_rektor:
        specific.append(_as_hit("https://uamd.edu.al/rektorati/", "Rektorati", provider="canonical"))
        specific.append(
            _as_hit("https://uamd.edu.al/fjala-e-rektorit/", "Fjala e Rektorit", provider="canonical")
        )

    # Live WP — for rector bio prefer name + rektorati, demote later via ranking
    try:
        wp_query = query
        if wants_erasmus(query):
            wp_query = "Erasmus mobilitet studentor shkëmbim"
        elif is_rektor and not person_name:
            wp_query = "Rektor Shkëlqim Fortuzi"
        elif person and person_name:
            wp_query = person_name
        elif wants_program_list(query):
            wp_query = f"{query} 2025 2026 program studimi"
        wp_hits = wp_site_search(wp_query, max_results=min(8, limit))
        if wp_hits:
            # Put meeting-news after canonical pages for leadership questions
            if is_rektor or person:
                ranked_wp = sorted(
                    wp_hits,
                    key=lambda h: (
                        0 if _is_newsish(h.get("url") or "", h.get("title") or "") else 1,
                        _freshness_score(h.get("url") or ""),
                    ),
                    reverse=True,
                )
                print(f"[search] wp_site_search → {len(ranked_wp)}")
                specific.extend(ranked_wp)
            else:
                print(f"[search] wp_site_search → {len(wp_hits)}")
                specific.extend(wp_hits)
    except Exception as exc:
        print(f"[search] wp_site_search failed: {exc}")

    deep_hits = [
        _as_hit(item["url"], item.get("title", ""), provider="deep")
        for item in deep_urls_for_question(query, limit=limit)
    ]
    if deep_hits:
        print(f"[search] deep map → {len(deep_hits)}")
        specific.extend(deep_hits)

    intent_hits = intent_seed_search(query, max_results=limit)
    if intent_hits:
        print(f"[search] intent seeds → {len(intent_hits)}")
        specific.extend(intent_hits)

    if person:
        for seed in (
            ("https://uamd.edu.al/rektorati/", "Rektorati"),
            ("https://uamd.edu.al/autoritetet-dhe-organet-drejtuese/", "Autoritetet"),
            (
                "https://uamd.edu.al/organika-e-personelit-akademik-ne-fakultetin-e-edukimit/",
                "Organika Edukim",
            ),
            (
                "https://uamd.edu.al/organika-e-personelit-akademik-ne-fakultetin-e-biznesit/",
                "Organika Biznes",
            ),
        ):
            specific.append(_as_hit(seed[0], seed[1], provider="intent"))

    strong = _prefer_fresh(specific, limit)
    if is_rektor:
        # Hard-pin authoritative leadership page first
        strong = _dedupe(
            [
                _as_hit("https://uamd.edu.al/rektorati/", "Rektorati", provider="canonical"),
                *strong,
            ],
            limit,
        )
    # Person/Erasmus/programs: stop after WP+map — skip slow DDG/crawl
    if len(strong) >= 3:
        results = _prefer_fresh(strong + fallback, limit)
        if is_rektor:
            results = _dedupe(
                [
                    _as_hit("https://uamd.edu.al/rektorati/", "Rektorati", provider="canonical"),
                    *results,
                ],
                limit,
            )
        print(f"[search] mid-path → {len(results)} urls")
        return results

    for provider in (crawl_uamd_site, search_tavily, search_serpapi, search_duckduckgo):
        try:
            if wants_erasmus(query) and provider is search_duckduckgo:
                q_for_provider = "Erasmus+ mobilitet studentor UAMD"
            elif person and person_name and provider is search_duckduckgo:
                q_for_provider = f'"{person_name}" site:uamd.edu.al'
            elif person and person_name:
                q_for_provider = person_name
            else:
                q_for_provider = query
            hits = provider(q_for_provider, max_results=limit)
        except Exception as exc:
            print(f"[search] provider {provider.__name__} failed: {exc}")
            hits = []
        if hits:
            print(f"[search] {provider.__name__} → {len(hits)}")
            specific.extend(hits)
        if len(_dedupe(specific, limit)) >= limit:
            break

    results = _prefer_fresh(specific + fallback, limit)
    if not results:
        results = _dedupe([_as_hit(u, "UAMD", provider="seed") for u in SEED_URLS], limit)
    print(
        f"[search] final → {len(results)} urls"
        + (f" | person={person_name}" if person_name else "")
    )
    return results
