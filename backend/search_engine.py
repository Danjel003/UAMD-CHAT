"""
UAMD GPT — Restricted web search for site:uamd.edu.al
Providers (in order): Tavily → SerpAPI → DuckDuckGo HTML fallback.
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

from scraper import is_uamd_url, normalize_url

load_dotenv()

SITE_FILTER = "site:uamd.edu.al"
MAX_RESULTS = 5
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Seed pages used only when search APIs return nothing
SEED_URLS = [
    "https://uamd.edu.al/",
    "https://uamd.edu.al/rreth-nesh/",
    "https://www.uamd.edu.al/",
]

_home_cache: dict[str, Any] = {"ts": 0.0, "candidates": []}
_home_lock = threading.Lock()
HOME_CACHE_TTL = 1800


def _dedupe_uamd(results: list[dict[str, Any]], limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in results:
        url = normalize_url(item.get("url") or "")
        if not url or not is_uamd_url(url) or url in seen:
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


def search_tavily(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key or api_key.startswith("tvly-your"):
        return []

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=f"{query} {SITE_FILTER}",
            search_depth="advanced",
            include_domains=["uamd.edu.al", "www.uamd.edu.al"],
            max_results=max_results,
        )
        results = []
        for r in response.get("results") or []:
            results.append(
                {
                    "url": r.get("url"),
                    "title": r.get("title"),
                    "snippet": r.get("content") or r.get("snippet") or "",
                    "provider": "tavily",
                }
            )
        return _dedupe_uamd(results, max_results)
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
        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=25)
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
        return _dedupe_uamd(results, max_results)
    except Exception as exc:
        print(f"[search] SerpAPI error: {exc}")
        return []


def _unwrap_ddg_redirect(href: str) -> str:
    """DuckDuckGo wraps links as //duckduckgo.com/l/?uddg=<encoded>."""
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])
    if href.startswith("//"):
        href = "https:" + href
    return href


def search_duckduckgo(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """HTML fallback — no API key required. Still restricted to uamd.edu.al results."""
    try:
        q = quote_plus(f"{query} {SITE_FILTER}")
        url = f"https://html.duckduckgo.com/html/?q={q}"
        resp = requests.get(
            url,
            timeout=25,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9,sq;q=0.8",
            },
        )
        # Some networks get challenge pages on POST; GET is more reliable
        if resp.status_code >= 400 or "result__a" not in resp.text:
            lite = f"https://lite.duckduckgo.com/lite/?q={q}"
            resp = requests.get(lite, timeout=25, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results: list[dict[str, Any]] = []

        # html.duckduckgo.com
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

        # lite.duckduckgo.com
        if not results:
            for a in soup.select("a.result-link"):
                href = a.get("href")
                if not href:
                    continue
                link = _unwrap_ddg_redirect(href)
                results.append(
                    {
                        "url": link,
                        "title": a.get_text(" ", strip=True),
                        "snippet": "",
                        "provider": "duckduckgo",
                    }
                )

        return _dedupe_uamd(results, max_results)
    except Exception as exc:
        print(f"[search] DuckDuckGo fallback error: {exc}")
        return []


def _load_home_candidates() -> list[dict[str, Any]]:
    with _home_lock:
        if _home_cache["candidates"] and time.time() - _home_cache["ts"] < HOME_CACHE_TTL:
            return list(_home_cache["candidates"])

    home = "https://uamd.edu.al/"
    resp = requests.get(home, timeout=12, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    candidates: list[dict[str, Any]] = [
        {
            "url": home,
            "title": "Universiteti Aleksandër Moisiu Durrës",
            "snippet": "",
            "provider": "crawl",
        }
    ]
    for a in soup.find_all("a", href=True):
        href = normalize_url(
            a["href"] if a["href"].startswith("http") else urljoin(home, a["href"])
        )
        if not is_uamd_url(href):
            continue
        title = a.get_text(" ", strip=True)
        candidates.append(
            {
                "url": href,
                "title": title or href,
                "snippet": "",
                "provider": "crawl",
            }
        )

    with _home_lock:
        _home_cache["ts"] = time.time()
        _home_cache["candidates"] = candidates
    return candidates


def crawl_uamd_site(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """
    Direct crawl of uamd.edu.al homepage + first-level links (cached).
    Used when external search APIs are unavailable.
    """
    tokens = [
        t
        for t in re.findall(r"[a-zçë0-9]{3,}", query.lower())
        if t
        not in {
            "the",
            "and",
            "per",
            "nga",
            "uamd",
            "edu",
            "www",
            "http",
            "https",
            "cilat",
            "cili",
            "cfare",
            "çfarë",
            "ka",
            "jane",
            "janë",
        }
    ]

    try:
        candidates = _load_home_candidates()
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in candidates:
            path = urlparse(item["url"]).path.lower()
            hay = f"{item['title']} {path}".lower()
            score = sum(1 for t in tokens if t in hay)
            if any(k in hay for k in ("fakultet", "pranim", "student", "program", "master", "bachelor")):
                if any(t.startswith("fakult") or t in {"pranim", "program", "master", "student"} for t in tokens):
                    score += 2
                elif "fakult" in " ".join(tokens):
                    score += 2
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = [item for _, item in scored] if scored else candidates
        return _dedupe_uamd(ranked, max_results)
    except Exception as exc:
        print(f"[search] Direct crawl error: {exc}")
        return _dedupe_uamd(
            [{"url": u, "title": "UAMD", "snippet": "", "provider": "seed"} for u in SEED_URLS],
            max_results,
        )


def seed_fallback(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    return crawl_uamd_site(query, max_results=max_results)


def search_uamd(query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """
    Search only within uamd.edu.al.
    Order: Tavily → SerpAPI → direct crawl (fast) → DuckDuckGo.
    """
    query = (query or "").strip()
    if not query:
        return []

    for provider in (search_tavily, search_serpapi):
        hits = provider(query, max_results=max_results)
        if hits:
            print(f"[search] Using provider={hits[0]['provider']} → {len(hits)} results")
            return hits

    # Local crawl is usually faster/more reliable than DDG for this domain
    crawl_hits = crawl_uamd_site(query, max_results=max_results)
    if crawl_hits and crawl_hits[0].get("provider") == "crawl":
        # If crawl found keyword-matching pages (not only SEED), use them
        print(f"[search] Using provider=crawl → {len(crawl_hits)} results")
        return crawl_hits

    ddg_hits = search_duckduckgo(query, max_results=max_results)
    if ddg_hits:
        print(f"[search] Using provider=duckduckgo → {len(ddg_hits)} results")
        return ddg_hits

    print("[search] Falling back to seed URLs")
    return crawl_hits or _dedupe_uamd(
        [{"url": u, "title": "UAMD", "snippet": "", "provider": "seed"} for u in SEED_URLS],
        max_results,
    )
