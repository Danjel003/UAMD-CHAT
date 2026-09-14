"""
UAMD GPT — Deep live RAG over uamd.edu.al.
Always searches deeply and answers from official pages; avoids empty refusals.

Copyright (c) 2026 Danjel Kalari. All rights reserved.
Author: Danjel Kalari
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from scraper import content_hash, fetch_many
from search_engine import search_uamd
from uamd_map import (
    catalog_context_for_question,
    department_urls,
    extract_person_name,
    wants_erasmus,
    wants_person_lookup,
    wants_program_list,
)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CACHE_FOLDER = Path(os.getenv("CACHE_FOLDER", BASE_DIR / "cache"))
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "local").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
TOP_K = int(os.getenv("TOP_K", "8"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "750"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))
MAX_CHUNKS_PER_DOC = int(os.getenv("MAX_CHUNKS_PER_DOC", "4"))
MAX_TOTAL_CHUNKS = int(os.getenv("MAX_TOTAL_CHUNKS", "24"))
MIN_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", "0.05"))
MAX_DOCS = int(os.getenv("MAX_DOCS", "7"))
USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "auto").lower()  # auto|always|never


NO_ANSWER = (
    "Nuk gjeta një përgjigje të saktë në faqen zyrtare të Universitetit "
    "'Aleksandër Moisiu' Durrës. Ju lutem kontaktoni universitetin për informacion zyrtar."
)

SYSTEM_PROMPT = (
    "Ti je UAMD GPT — asistent informues zyrtar i Universitetit 'Aleksandër Moisiu' Durrës.\n"
    "Shkruaj si komunikim INSTITUCIONAL: paragrafë të artikuluar, të saktë dhe të bukur.\n\n"
    "Stil i detyrueshëm:\n"
    "1) Vetëm tekst i rrjedhshëm në paragrafë. MOS përdor Markdown: as ##, as **, as *, as -, as lista me pika, as emoji.\n"
    "2) Ton zyrtar, i qartë dhe profesional — si njoftim/informacion i universitetit.\n"
    "3) Vetëm fakte nga konteksti. Mos shpik. Mos shkruaj 'nuk ka informacion për formimin/karrierën' si fusha boshe.\n"
    "4) Përgjigju drejtpërdrejt pyetjes. Pa marketing dhe pa fraza të përgjithshme.\n"
    "5) PRIORITETO informacionin më të ri (2025-2026). Në konflikt, zgjidh versionin e ri.\n"
    "6) Për lista programesh: përmendi ato në fjali/paragrafë të ndara sipas ciklit, jo me shenja.\n"
    "7) Mos shto seksion 'Burime' në tekst — burimet shfaqen veçmas.\n"
    "8) Erasmus/mobilitet → mos listo programe fakulteti; fokus te shkëmbimet, thirrjet dhe kontaktet.\n"
    "9) Shqip i pastër, i artikuluar, i saktë."
)

OUT_OF_SCOPE = (
    "UAMD GPT shërben për informacione të Universitetit 'Aleksandër Moisiu' Durrës. "
    "Mund të pyesësh për fakultete, programe, pranime, orare, kontakt, rregullore, etj. "
    "Për fillim: https://uamd.edu.al/"
)

PERSONAL_DATA_REFUSAL = (
    "Nuk mund të përgjigjem sepse nuk kam informacion për të dhëna personale "
    "dhe informacion jashtë korpusit publik të Universitetit 'Aleksandër Moisiu' Durrës. "
    "Mund të pyesësh për informacione zyrtare publike në uamd.edu.al "
    "(fakultete, programe, pranime, Erasmus, kontakt, etj.)."
)

_lock = threading.Lock()
_engine: "RAGEngine | None" = None


def looks_out_of_scope(question: str) -> bool:
    """Very strict: only reject clearly non-university chatter."""
    q = question.lower().strip()
    if len(q) < 2:
        return True
    off = [
        "si je", "hello", "hi ", "hey", "moti", "football", "futboll", "bitcoin",
        "recetë", "recete", "shaka", "joke", "poezi", "kush fitoi", "horoskop",
    ]
    if any(p in q for p in off):
        # still allow if university mentioned
        if any(k in q for k in ("uamd", "universitet", "moisiu", "fakultet", "student")):
            return False
        return True
    return False


def looks_like_personal_data(question: str) -> bool:
    """Refuse private student/staff records not available in the public corpus."""
    q = (question or "").lower().strip()
    personal_signals = [
        "nota mesatare",
        "notën mesatare",
        "noten mesatare",
        "mesatarja e student",
        "mesatarja ime",
        "sa kam mesatare",
        "sa eshte nota",
        "sa është nota",
        "notat e student",
        "transkript",
        "transcript",
        "numri i amzës",
        "numri i amzes",
        "id studenti",
        "id e studentit",
        "password",
        "fjalëkalim",
        "fjalekalim",
        "pitagora password",
        "llogaria ime",
        "të dhëna personale",
        "te dhena personale",
        "paga e",
        "salari",
        "numri personal",
        "nid",
    ]
    if any(s in q for s in personal_signals):
        return True
    # e.g. "nota mesatare e studentit X" / "mesatarja e Anës"
    if re.search(r"\b(nota|notën|noten|mesatar\w*)\b.*\b(student\w*|emri|emër)\b", q):
        return True
    if re.search(r"\b(studentit|studentes|studentës)\s+[a-zçë]{2,}", q) and any(
        k in q for k in ("nota", "mesatar", "notat", "amz")
    ):
        return True
    return False


def wants_pdfs(question: str) -> bool:
    q = question.lower()
    return any(
        k in q
        for k in (
            "pdf", "dokument", "rregullore", "statut", "vendim", "udhëzim", "udhezim",
            "program", "programe", "kuota", "excel", "tabel", "tarif", "orar",
        )
    )


_FLUFF_LINE = re.compile(
    r"(?i)^\s*("
    r"në botën e sotme.*"
    r"|universiteti (ynë )?ofro(n|jnë) mundësi.*"
    r"|është (një )?institucion i rëndësishëm.*"
    r"|me kënaqësi ju informoj.*"
    r"|siç dihet.*"
    r"|në përfundim,.*"
    r"|shpresoj që kjo përgjigje.*"
    r"|informacion(e|i)? të detajuara.*nuk janë të disponueshme.*"
    r"|burime\s*:?\s*$"
    r")\s*$"
)


def _polish_answer(text: str) -> str:
    """Institutional plain prose: strip markdown and fluff."""
    if not text:
        return ""
    # Convert markdown links to plain label; drop trailing "Burime" URL dumps
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    text = re.sub(r"(?im)^\s*#{1,6}\s*", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"(?m)^\s*[-•*]\s+", "", text)
    text = re.sub(r"(?im)^\s*burime\s*:?\s*$", "", text)
    text = re.sub(r"(?im)^\s*https?://\S+\s*$", "", text)

    lines: list[str] = []
    blank = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if _FLUFF_LINE.match(line):
            continue
        if not line.strip():
            blank += 1
            if blank <= 1:
                lines.append("")
            continue
        blank = 0
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def simple_split(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    parts: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            window = text[start:end]
            break_at = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if break_at > chunk_size * 0.4:
                end = start + break_at + 1
        chunk = text[start:end].strip()
        if chunk:
            parts.append(chunk)
        if end >= n:
            break
        start = max(0, end - overlap)
    return parts


def _keyword_score(question: str, text: str, person_name: str = "") -> float:
    q_tokens = [
        t
        for t in re.findall(r"[a-zçë0-9]{3,}", question.lower())
        if t not in {"the", "and", "per", "nga", "nje", "një", "kush", "eshte", "është"}
    ]
    hay = text.lower()
    score = 0.0
    if q_tokens:
        hits = sum(1 for t in q_tokens if t in hay)
        score = hits / max(len(q_tokens), 1)
    if person_name:
        name = person_name.lower().strip()
        if name and name in hay:
            score += 1.0
        else:
            parts = [p for p in name.split() if len(p) >= 3]
            if parts and all(p in hay for p in parts):
                score += 0.8
    return min(score, 1.5)


_GENERIC_SOURCE_PATHS = {
    "",
    "/",
    "/faqja-kryesore",
    "/kendi-i-maturantit",
    "/biblioteka-universitare",
    "/kontakto",
}

_CANONICAL_PATHS = {
    "/rektorati",
    "/fjala-e-rektorit",
    "/autoritetet-dhe-organet-drejtuese",
    "/misioni-dhe-vizioni",
    "/kalendari-akademik",
    "/sekretarite-mesimore",
    "/marredheniet-me-jashte-dhe-projektet",
}


def _url_path(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return (urlparse(url).path or "/").rstrip("/") or "/"
    except Exception:
        return "/"


def _is_generic_source(url: str) -> bool:
    path = _url_path(url)
    if path in _GENERIC_SOURCE_PATHS or path == "/":
        return True
    # Bare homepage variants
    u = (url or "").rstrip("/").lower()
    return u in {"https://uamd.edu.al", "http://uamd.edu.al"}


def _is_meeting_news(url: str, title: str = "") -> bool:
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


def _doc_mentions_person(doc: dict[str, Any], person_name: str) -> bool:
    if not person_name:
        return True
    name = person_name.lower().strip()
    hay = f"{doc.get('title') or ''} {doc.get('text') or ''} {doc.get('content') or ''}".lower()
    if name in hay:
        return True
    parts = [p for p in name.split() if len(p) >= 3]
    return bool(parts) and all(p in hay for p in parts)


def _authority_score(
    url: str,
    title: str,
    text: str,
    question: str,
    person_name: str = "",
    base: float = 0.0,
) -> float:
    """Prefer canonical pages that actually contain the answer facts."""
    q = (question or "").lower()
    path = _url_path(url)
    score = float(base)
    hay = f"{title} {text}".lower()

    if _is_generic_source(url):
        score -= 40

    if path in _CANONICAL_PATHS:
        score += 18

    # Leadership / rector → rektorati is the authoritative bio page
    if any(k in q for k in ("rektor", "zv. rektor", "zëvendës rektor", "rektorat")):
        if path == "/rektorati":
            score += 55
        elif path == "/fjala-e-rektorit":
            score += 20
        elif _is_meeting_news(url, title):
            score -= 35

    if person_name:
        if _doc_mentions_person({"title": title, "text": text}, person_name):
            score += 30
        else:
            score -= 45
        if _is_meeting_news(url, title) and path not in _CANONICAL_PATHS:
            score -= 15

    if wants_program_list(question):
        if "fakultet" in path or "departament" in path:
            score += 25
        if _is_meeting_news(url, title):
            score -= 20

    if wants_erasmus(question):
        if "marredheniet-me-jashte" in path or "erasmus" in path or "projekt" in path:
            score += 30

    # Prefer shorter official paths over long news slugs
    depth = path.count("/")
    if depth <= 2 and "wp-content" not in (url or "").lower():
        score += 4
    if len(path) > 80:
        score -= 8

    # Content must be useful
    if len((text or "").strip()) < 80:
        score -= 10

    return score


def _pick_precise_sources(
    question: str,
    ranked_chunks: list[dict[str, Any]],
    docs: list[dict[str, Any]],
    person_name: str = "",
    limit: int = 3,
) -> list[str]:
    """Return only URLs that actually support the answer — not generic hubs."""
    by_url: dict[str, dict[str, Any]] = {}
    for d in docs:
        u = d.get("url") or ""
        if u:
            by_url[u] = d

    scored: list[tuple[float, str]] = []
    seen: set[str] = set()

    for c in ranked_chunks:
        url = c.get("url") or ""
        if not url or url in seen or url == "https://uamd.edu.al/" or _is_generic_source(url):
            continue
        if url.startswith("catalog") or c.get("id") == "catalog":
            continue
        doc = by_url.get(url) or {}
        title = c.get("title") or doc.get("title") or ""
        text = c.get("content") or doc.get("text") or ""
        if person_name and not _doc_mentions_person(
            {"title": title, "text": text, "content": c.get("content") or ""},
            person_name,
        ):
            continue
        s = _authority_score(
            url,
            title,
            text,
            question,
            person_name=person_name,
            base=float(c.get("score") or c.get("kw") or 0) * 10,
        )
        if s < 5:
            continue
        seen.add(url)
        scored.append((s, url))

    # Fill from docs if needed (still authority-filtered)
    if len(scored) < limit:
        for d in docs:
            url = d.get("url") or ""
            if not url or url in seen or _is_generic_source(url):
                continue
            if person_name and not _doc_mentions_person(d, person_name):
                continue
            s = _authority_score(
                url,
                d.get("title") or "",
                d.get("text") or "",
                question,
                person_name=person_name,
                base=0,
            )
            if s < 8:
                continue
            seen.add(url)
            scored.append((s, url))

    scored.sort(key=lambda x: x[0], reverse=True)

    # For leadership/role questions keep only strong canonical pages
    q = (question or "").lower()
    if any(k in q for k in ("rektor", "rektorat", "zv. rektor", "zëvendës rektor")):
        strong = [(s, u) for s, u in scored if s >= 40 or _url_path(u) in _CANONICAL_PATHS]
        if strong:
            scored = strong
            limit = min(limit, 2)

    out = [u for _, u in scored[:limit]]

    # Last resort: best non-generic doc
    if not out:
        for d in docs:
            url = d.get("url") or ""
            if url and not _is_generic_source(url):
                out.append(url)
                break
    return out


def _sort_docs_by_authority(
    docs: list[dict[str, Any]], question: str, person_name: str = ""
) -> list[dict[str, Any]]:
    return sorted(
        docs,
        key=lambda d: _authority_score(
            d.get("url") or "",
            d.get("title") or "",
            d.get("text") or "",
            question,
            person_name=person_name,
        ),
        reverse=True,
    )


class RAGEngine:
    def __init__(self) -> None:
        self._embedding_model = None
        self._embedding_backend = EMBEDDING_BACKEND
        self._openai = None
        self._ready = False
        self._query_cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl = int(os.getenv("QUERY_CACHE_TTL", "120"))
        self._embed_cache: dict[str, np.ndarray] = {}
        self._embed_cache_lock = threading.Lock()

    def initialize(self) -> None:
        with _lock:
            if self._ready:
                return
            self._openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            backend = os.getenv("EMBEDDING_BACKEND", EMBEDDING_BACKEND).lower()
            self._embedding_backend = backend
            if backend == "openai":
                print("[rag] Using OpenAI embeddings (production/light mode)...")
            else:
                print("[rag] Loading local embedding model...")
                from sentence_transformers import SentenceTransformer

                cache_dir = str(CACHE_FOLDER / "embeddings")
                Path(cache_dir).mkdir(parents=True, exist_ok=True)
                self._embedding_model = SentenceTransformer(
                    EMBEDDING_MODEL, cache_folder=cache_dir, trust_remote_code=True
                )
                self._embedding_model.encode(["uamd warmup"], normalize_embeddings=True)
            self._ready = True
            print(f"[rag] Ready (backend={self._embedding_backend}).")

    def _chunk_documents(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for doc in docs:
            lead = f"{doc.get('title') or ''}\n{doc.get('url') or ''}\n{(doc.get('text') or '')[:700]}".strip()
            if len(lead) >= 40:
                chunks.append(
                    {
                        "id": f"{content_hash(doc['url'])}_lead",
                        "content": lead,
                        "url": doc["url"],
                        "title": doc.get("title") or doc["url"],
                    }
                )
            pieces = simple_split(doc["text"])
            kept = 0
            for i, content in enumerate(pieces):
                content = content.strip()
                if len(content) < 40:
                    continue
                chunks.append(
                    {
                        "id": f"{content_hash(doc['url'])}_{i}",
                        "content": content,
                        "url": doc["url"],
                        "title": doc.get("title") or doc["url"],
                    }
                )
                kept += 1
                if kept >= MAX_CHUNKS_PER_DOC:
                    break
            if len(chunks) >= MAX_TOTAL_CHUNKS:
                break
        return chunks[:MAX_TOTAL_CHUNKS]

    def _encode_openai(self, texts: list[str]) -> np.ndarray:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = texts[i : i + 64]
            resp = self._openai.embeddings.create(model=OPENAI_EMBEDDING_MODEL, input=batch)
            for row in sorted(resp.data, key=lambda x: x.index):
                vec = np.asarray(row.embedding, dtype=np.float32)
                out.append((vec / (np.linalg.norm(vec) + 1e-12)).tolist())
        return np.asarray(out, dtype=np.float32)

    def _embed(self, texts: list[str]) -> np.ndarray:
        vectors: list[np.ndarray | None] = [None] * len(texts)
        missing_idx: list[int] = []
        missing_texts: list[str] = []
        with self._embed_cache_lock:
            for i, t in enumerate(texts):
                key = content_hash(t)
                cached = self._embed_cache.get(key)
                if cached is not None:
                    vectors[i] = cached
                else:
                    missing_idx.append(i)
                    missing_texts.append(t)
        if missing_texts:
            if self._embedding_backend == "openai":
                encoded = self._encode_openai(missing_texts)
            else:
                encoded = self._embedding_model.encode(
                    missing_texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True
                )
            with self._embed_cache_lock:
                for i, vec in zip(missing_idx, encoded):
                    arr = np.asarray(vec, dtype=np.float32)
                    vectors[i] = arr
                    self._embed_cache[content_hash(texts[i])] = arr
                    if len(self._embed_cache) > 5000:
                        for k in list(self._embed_cache.keys())[:1000]:
                            self._embed_cache.pop(k, None)
        return np.vstack(vectors)

    def _semantic_rerank(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        top_k: int = TOP_K,
        person_name: str = "",
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []

        # Fast keyword pre-rank (no API) — boost exact person-name hits
        pre: list[dict[str, Any]] = []
        for chunk in chunks:
            kw = _keyword_score(
                question,
                chunk["content"] + " " + (chunk.get("title") or ""),
                person_name=person_name,
            )
            auth = _authority_score(
                chunk.get("url") or "",
                chunk.get("title") or "",
                chunk.get("content") or "",
                question,
                person_name=person_name,
                base=0,
            )
            item = dict(chunk)
            item["kw"] = kw
            item["auth"] = auth
            item["score"] = kw + max(auth, 0) / 50.0
            pre.append(item)
        pre.sort(key=lambda x: x["score"], reverse=True)

        mode = USE_EMBEDDINGS
        strong_kw = pre and pre[0]["kw"] >= 0.35
        use_emb = mode == "always" or (mode == "auto" and not strong_kw and not person_name)

        if not use_emb or mode == "never":
            return pre[:top_k]

        candidates = pre[: max(top_k + 4, 10)]
        q_vec = self._embed([question])[0]
        doc_vecs = self._embed([c["content"] for c in candidates])
        for i, chunk in enumerate(candidates):
            semantic = float(doc_vecs[i] @ q_vec)
            auth = float(chunk.get("auth") or 0) / 50.0
            chunk["score"] = 0.55 * semantic + 0.25 * float(chunk.get("kw") or 0) + 0.2 * auth
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]

    def _fallback_from_docs(self, question: str, docs: list[dict[str, Any]], search_hits: list[dict[str, Any]]) -> str:
        """Constructive answer when model refuses or context is thin."""
        links = []
        for d in docs[:5]:
            title = d.get("title") or "Faqe UAMD"
            links.append(f"- {title}: {d.get('url')}")
        if not links:
            for h in search_hits[:5]:
                links.append(f"- {h.get('title') or 'UAMD'}: {h.get('url')}")
        snippet = ""
        for d in docs:
            text = (d.get("text") or "").strip()
            if len(text) > 120:
                snippet = text[:280].replace("\n", " ")
                break
        body = (
            f"Bazuar në faqet zyrtare të UAMD, ja informacioni më i afërt për pyetjen tënde.\n"
        )
        if snippet:
            body += f"\n{snippet}...\n"
        body += "\nMund të kontrollosh këto burime zyrtare:\n" + "\n".join(links)
        body += "\n\nKontakt: info@uamd.edu.al | https://uamd.edu.al/"
        return body

    def _generate(
        self,
        question: str,
        contexts: list[dict[str, Any]],
        source_docs: list[dict[str, Any]] | None = None,
        search_hits: list[dict[str, Any]] | None = None,
        catalog_block: str = "",
    ) -> str:
        if not contexts and not source_docs and not catalog_block:
            return NO_ANSWER

        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key or api_key.startswith("sk-your"):
            raise RuntimeError("Incorrect API key provided: OPENAI_API_KEY is missing or placeholder.")

        self._openai = OpenAI(api_key=api_key)

        is_programs = wants_program_list(question)
        is_erasmus = wants_erasmus(question)
        is_person = wants_person_lookup(question)
        person_name = extract_person_name(question) if is_person else ""
        deep_q = is_programs or is_erasmus or is_person

        pages_block = ""
        docs_for_list = source_docs or []
        page_limit = 4 if deep_q else 3
        # Only list the pages we will actually cite (precise, not hubs)
        cite_docs = [
            d
            for d in docs_for_list
            if d.get("url") and not _is_generic_source(d["url"])
        ][:page_limit]
        if not cite_docs and search_hits:
            cite_docs = [
                {"title": h.get("title"), "url": h.get("url")}
                for h in search_hits
                if h.get("url") and not _is_generic_source(h["url"])
            ][:page_limit]
        if cite_docs:
            lines = [f"- {d.get('title') or 'Faqe UAMD'}: {d.get('url')}" for d in cite_docs]
            pages_block = (
                "Faqet zyrtare që duhet të përdorësh (prioriteti sipas rendit):\n"
                + "\n".join(lines)
                + "\n\n"
            )

        ctx_limit = 10 if deep_q else 6
        ctx_chars = 2200 if is_person else (1800 if deep_q else 1200)
        context_block = "\n\n".join(
            f"[Burimi: {c.get('title') or 'UAMD'}] ({c.get('url')})\n{(c.get('content') or '')[:ctx_chars]}"
            for c in contexts[:ctx_limit]
        )

        catalog_section = ""
        if catalog_block:
            catalog_section = (
                "LISTË NDIHMËSE PROGRAMESH (përdore vetëm nëse mungon në faqet live; "
                "në konflikt, ZGJIDH faqet e reja zyrtare):\n"
                f"{catalog_block}\n\n"
            )

        extra_rules = ""
        max_tokens = 550
        if is_programs:
            max_tokens = 850
            extra_rules = (
                "- Shkruaj në paragrafë institucionale: fillimisht fakulteti, pastaj ciklet.\n"
                "- Për çdo cikël (Bachelor, Master Shkencor, Master Profesional, profesional 2-vjeçar) "
                "një paragraf që liston programet me emra të plotë, të ndara me presje.\n"
                "- Pa shenja Markdown dhe pa lista me pika.\n"
            )
        elif is_erasmus:
            max_tokens = 750
            extra_rules = (
                "- Paragrafë të qartë për Erasmus+/mobilitet: çfarë ofrohet, si aplikohen, kontakte.\n"
                "- Pa Markdown. Vetëm tekst i rrjedhshëm zyrtar.\n"
            )
        elif is_person:
            max_tokens = 650
            who = person_name or "këtij personi"
            extra_rules = (
                f"- Shkruaj një biografi të shkurtër zyrtare për {who} në 1–3 paragrafë.\n"
                "- Përfshi vetëm faktet e gjetura (titull, rol, njësi, aktivitet). "
                "Mos krijo fusha boshe për formim/karrierë nëse nuk i ke.\n"
                "- Shembull stili: «Prof. Dr. … është Rektor i Universitetit … . Në këtë rol … .»\n"
                "- Pa Markdown, pa lista, pa yje, pa thurje.\n"
            )
        else:
            extra_rules = (
                "- 1–3 paragrafë të artikuluar që përgjigjen saktësisht pyetjes.\n"
                "- Pa Markdown dhe pa lista me shenja.\n"
            )

        user_prompt = (
            f"{pages_block}"
            f"{catalog_section}"
            f"Ekstrakte nga burimet zyrtare:\n\n{context_block}\n\n"
            f"Pyetja: {question}\n\n"
            "Udhëzime të detyrueshme:\n"
            "- Përgjigju NË SHQIP, në stil INSTITUCIONAL, me PARAGRAFË të bukur dhe të saktë.\n"
            "- Bazohu te faqet kanonike të listuara sipër (p.sh. Rektorati, fakulteti, departamenti), "
            "jo te njoftime takimesh kur ato nuk shtojnë fakte biografike.\n"
            "- MOS përdor ##, **, *, - , lista, emoji ose seksion Burime.\n"
            "- ZERO tekst kot. PRIORITETO 2025-2026.\n"
            "- MOS përdor frazën 'Nuk gjeta një përgjigje të saktë'.\n"
            f"{extra_rules}"
        )

        response = self._openai.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.25,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        answer = (response.choices[0].message.content or "").strip()
        answer = _polish_answer(answer)
        if (not answer) or ("nuk gjeta një përgjigje" in answer.lower()):
            if catalog_block:
                return _polish_answer(catalog_block)
            return self._fallback_from_docs(question, docs_for_list or [], search_hits or [])
        return answer

    def ask(self, question: str) -> dict[str, Any]:
        started = time.time()
        if not self._ready:
            self.initialize()

        question = (question or "").strip()
        if not question:
            return {"answer": "Ju lutem shkruani një pyetje.", "sources": []}

        if looks_out_of_scope(question):
            return {"answer": OUT_OF_SCOPE, "sources": ["https://uamd.edu.al/"]}

        if looks_like_personal_data(question):
            return {
                "answer": PERSONAL_DATA_REFUSAL,
                "sources": ["https://uamd.edu.al/"],
            }

        cache_key = re.sub(r"\s+", " ", question.lower()).strip()
        cached = self._query_cache.get(cache_key)
        if cached and time.time() - cached["ts"] < self._cache_ttl:
            if "nuk gjeta një përgjigje" not in (cached.get("answer") or "").lower():
                return {"answer": cached["answer"], "sources": cached["sources"], "cached": True}

        is_programs = wants_program_list(question)
        is_erasmus = wants_erasmus(question)
        is_person = wants_person_lookup(question)
        person_name = extract_person_name(question) if is_person else ""
        wide = is_programs or is_erasmus or is_person

        search_hits = search_uamd(question, max_results=10 if is_person else (12 if wide else max(TOP_K, 8)))
        if not search_hits:
            search_hits = [
                {"url": "https://uamd.edu.al/", "title": "UAMD", "snippet": "", "provider": "fallback"}
            ]

        urls = [h["url"] for h in search_hits]
        need_pdfs = wants_pdfs(question) or is_programs
        expand = is_programs or any(
            k in question.lower()
            for k in ("bachelor", "master", "dega", "deget", "fakultet")
        )
        # Phase 1: enough pages for a convincing answer; phase 2 only if person missing
        max_docs = 8 if is_person else (10 if wide else MAX_DOCS)
        docs = fetch_many(
            urls,
            max_docs=max_docs,
            include_pdfs=need_pdfs,
            expand_faculty=expand and not is_person,
            prefer_name=person_name,
            use_cache=False,
        )

        def _name_hit(doc: dict[str, Any]) -> int:
            if not person_name:
                return 0
            name_l = person_name.lower()
            parts = [p for p in name_l.split() if len(p) >= 3]
            hay = f"{doc.get('title') or ''} {doc.get('text') or ''}".lower()
            if name_l in hay:
                return 2
            if parts and all(p in hay for p in parts):
                return 1
            return 0

        # Phase 2 (person only): scan department pages if name not found yet
        if is_person and person_name and not any(_name_hit(d) for d in docs):
            dept_urls = [d["url"] for d in department_urls()]
            more = fetch_many(
                dept_urls,
                max_docs=18,
                include_pdfs=False,
                expand_faculty=False,
                prefer_name=person_name,
                use_cache=False,
            )
            docs.extend(more)

        if is_person and person_name and docs:
            docs = sorted(docs, key=_name_hit, reverse=True)
            hits = [d for d in docs if _name_hit(d) > 0]
            if hits:
                # Keep rich bios (not just 1 thin snippet)
                docs = hits[:5]

        # Prefer canonical pages (e.g. /rektorati/) over meeting news
        docs = _sort_docs_by_authority(docs, question, person_name=person_name)

        catalog_block = catalog_context_for_question(question)

        if not docs and not catalog_block:
            answer = (
                "Po kërkova në faqen zyrtare të UAMD. Mund të fillosh nga këto burime:\n"
                "- https://uamd.edu.al/\n"
                "- https://uamd.edu.al/kendi-i-maturantit/\n"
                "- https://admissions.prime-solutions.al/\n"
                "Kontakt: info@uamd.edu.al"
            )
            return {"answer": answer, "sources": urls[:5]}

        if wide:
            chunks: list[dict[str, Any]] = []
            docs_for_chunks = docs[:6] if is_person else docs
            for doc in docs_for_chunks:
                text = doc.get("text") or ""
                if is_person and person_name:
                    low = text.lower()
                    idx = low.find(person_name.lower())
                    if idx < 0:
                        for p in person_name.lower().split():
                            if len(p) >= 3 and p in low:
                                idx = low.find(p)
                                break
                    if idx >= 0:
                        # Wider window = deeper biography
                        start = max(0, idx - 500)
                        end = min(len(text), idx + 2200)
                        text = text[start:end]
                lead = (
                    f"{doc.get('title') or ''}\n{doc.get('url') or ''}\n"
                    f"{text[:2000]}"
                ).strip()
                if len(lead) >= 40:
                    chunks.append(
                        {
                            "id": f"{content_hash(doc['url'])}_lead",
                            "content": lead,
                            "url": doc["url"],
                            "title": doc.get("title") or doc["url"],
                        }
                    )
                for i, content in enumerate(
                    simple_split(doc.get("text") or "", chunk_size=850, overlap=90)[:4]
                ):
                    if len(content.strip()) < 40:
                        continue
                    chunks.append(
                        {
                            "id": f"{content_hash(doc['url'])}_{i}",
                            "content": content,
                            "url": doc["url"],
                            "title": doc.get("title") or doc["url"],
                        }
                    )
            if catalog_block:
                chunks.insert(
                    0,
                    {
                        "id": "catalog",
                        "content": catalog_block,
                        "url": "https://uamd.edu.al/",
                        "title": "Lista e plotë e programeve (katalog zyrtar)",
                    },
                )
            ranked = self._semantic_rerank(
                question, chunks[:50], top_k=12, person_name=person_name
            )
        else:
            chunks = self._chunk_documents(docs)
            ranked = self._semantic_rerank(question, chunks, top_k=TOP_K)

        relevant = ranked[: min(12 if wide else TOP_K, len(ranked))]

        # Keep generation context on authoritative pages only
        precise_urls = _pick_precise_sources(
            question, relevant, docs, person_name=person_name, limit=4
        )
        if precise_urls:
            precise_set = set(precise_urls)
            filtered = [c for c in relevant if c.get("url") in precise_set]
            if filtered:
                relevant = filtered
            docs_for_gen = [d for d in docs if d.get("url") in precise_set] or docs[:3]
        else:
            docs_for_gen = docs[:3]

        answer = self._generate(
            question,
            relevant,
            source_docs=docs_for_gen,
            search_hits=search_hits,
            catalog_block=catalog_block,
        )

        sources = _pick_precise_sources(
            question, relevant, docs_for_gen, person_name=person_name, limit=3
        )
        if not sources:
            sources = [
                d["url"]
                for d in docs_for_gen
                if d.get("url") and not _is_generic_source(d["url"])
            ][:3]

        result = {"answer": answer, "sources": sources}
        # Don't cache empty person lookups — allow retry after scrape improvements
        cacheable = "nuk gjeta një përgjigje" not in answer.lower()
        if cacheable and "nuk u gjet informacion publik" not in answer.lower():
            self._query_cache[cache_key] = {**result, "ts": time.time()}

        print(
            f"[rag] answered in {time.time() - started:.2f}s | docs={len(docs)} "
            f"chunks={len(chunks)} sources={len(result['sources'])}"
        )
        return result


def get_engine() -> RAGEngine:
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = RAGEngine()
    return _engine
