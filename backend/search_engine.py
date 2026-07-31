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

load_dotenv()

SITE_FILTER = "site:uamd.edu.al"
MAX_RESULTS = 5
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SEED_URLS = [
    "https://uamd.edu.al/",
    "https://uamd.edu.al/faqja-kryesore/",
    "https://uamd.edu.al/misioni-dhe-vizioni/",
]

# Curated official pages for common intents (accuracy boost)
INTENT_SEEDS: list[tuple[list[str], list[dict[str, str]]]] = [
    (
        ["fti", "teknologjis", "teknologji informacioni", "informatik", "softuer", "program studimi", "programe studimi", "cikli", "bachelor", "master"],
        [
            {"url": "https://uamd.edu.al/fakulteti-i-teknologjise-se-informacionit/", "title": "Fakulteti i Teknologjisë së Informacionit (FTI)"},
            {"url": "https://uamd.edu.al/departamenti-i-teknologjise-se-informacionit/", "title": "Departamenti i Teknologjisë së Informacionit"},
            {"url": "https://uamd.edu.al/wp-content/uploads/2024/04/FTI.xlsx", "title": "Programet e studimit FTI (tabelë zyrtare)"},
            {"url": "https://uamd.edu.al/fakulteti-i-biznesit/", "title": "Fakulteti i Biznesit"},
            {"url": "https://uamd.edu.al/fakulteti-i-edukimit/", "title": "Fakulteti i Edukimit"},
        ],
    ),
    (
        ["fakultet", "fakulteti", "fakultetet", "akademi", "dega", "deget"],
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
        ["orar", "orari", "kalendar", "semest"],
        [
            {"url": "https://uamd.edu.al/orari-2/", "title": "Orari"},
            {"url": "https://uamd.edu.al/kalendari-akademik/", "title": "Kalendari Akademik"},
        ],
    ),
    (
        ["rektor", "administrat", "rektorat", "mision", "vizion", "rreth"],
        [
            {"url": "https://uamd.edu.al/faqja-kryesore/", "title": "Rreth Nesh"},
            {"url": "https://uamd.edu.al/misioni-dhe-vizioni/", "title": "Misioni dhe Vizioni"},
            {"url": "https://uamd.edu.al/rektorati/", "title": "Rektorati"},
            {"url": "https://uamd.edu.al/fjala-e-rektorit/", "title": "Fjala e Rektorit"},
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
HOME_CACHE_TTL = 1800


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
    hits: list[dict[str, Any]] = []
    for keywords, pages in INTENT_SEEDS:
        if any(k in q for k in keywords):
            for p in pages:
                hits.append(_as_hit(p["url"], p.get("title", ""), provider="intent"))
    # Always bias with homepage for university questions
    if any(k in q for k in ("uamd", "universitet", "moisiu", "durrës", "durres")):
        hits.insert(0, _as_hit("https://uamd.edu.al/", "Universiteti Aleksandër Moisiu Durrës", provider="intent"))
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
            timeout=20,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if resp.status_code >= 400 or "result__a" not in resp.text:
            resp = requests.get(
                f"https://lite.duckduckgo.com/lite/?q={q}",
                timeout=20,
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


def wp_site_search(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """Use the university WordPress search endpoint."""
    try:
        url = f"https://uamd.edu.al/?s={quote_plus(query)}"
        resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results: list[dict[str, Any]] = []
        for a in soup.select("article h2 a, h2.entry-title a, .search-results a"):
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
        return _dedupe(results, max_results)
    except Exception as exc:
        print(f"[search] WP search error: {exc}")
        return []


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
    Hybrid search prioritized for accuracy on common university questions.
    """
    query = (query or "").strip()
    if not query:
        return []

    merged: list[dict[str, Any]] = []

    intent_hits = intent_seed_search(query, max_results=max_results)
    if intent_hits:
        print(f"[search] intent seeds → {len(intent_hits)}")
        merged.extend(intent_hits)

    for provider in (search_tavily, search_serpapi, wp_site_search, crawl_uamd_site, search_duckduckgo):
        try:
            hits = provider(query, max_results=max_results)
        except Exception as exc:
            print(f"[search] provider {provider.__name__} failed: {exc}")
            hits = []
        if hits:
            print(f"[search] {provider.__name__} → {len(hits)}")
            merged.extend(hits)
        if len(_dedupe(merged, max_results)) >= max_results and intent_hits:
            break

    results = _dedupe(merged, max_results)
    if not results:
        results = _dedupe([_as_hit(u, "UAMD", provider="seed") for u in SEED_URLS], max_results)
    print(f"[search] final → {len(results)} urls")
    return results
