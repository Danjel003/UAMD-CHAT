"""
UAMD GPT — Deep live RAG over uamd.edu.al.
Always searches deeply and answers from official pages; avoids empty refusals.
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

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CACHE_FOLDER = Path(os.getenv("CACHE_FOLDER", BASE_DIR / "cache"))
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "local").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
TOP_K = int(os.getenv("TOP_K", "10"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))
MAX_CHUNKS_PER_DOC = int(os.getenv("MAX_CHUNKS_PER_DOC", "6"))
MAX_TOTAL_CHUNKS = int(os.getenv("MAX_TOTAL_CHUNKS", "36"))
MIN_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", "0.05"))
MAX_DOCS = int(os.getenv("MAX_DOCS", "12"))

NO_ANSWER = (
    "Nuk gjeta një përgjigje të saktë në faqen zyrtare të Universitetit "
    "'Aleksandër Moisiu' Durrës. Ju lutem kontaktoni universitetin për informacion zyrtar."
)

SYSTEM_PROMPT = (
    "Ti je UAMD GPT, asistenti zyrtar informues i Universitetit 'Aleksandër Moisiu' Durrës. "
    "Detyra jote: jep GJITHMONË një përgjigje të dobishme duke u bazuar në konteksting e faqeve zyrtare. "
    "Rregulla:\n"
    "1) Përdor vetëm informacionin e kontekstit (uamd.edu.al / admissions).\n"
    "2) Nëse nuk ke numrin/datën e saktë, jep informacionin më të afërt që ke + linkun zyrtar ku të vazhdohet.\n"
    "3) MOS thuaj 'Nuk gjeta një përgjigje…' kur ke të paktën një fakt, listë, email, emër, link ose udhëzim.\n"
    "4) Përgjigje të shkurtra, konkrete, në shqip.\n"
    "5) Mos shpik fakte që nuk janë në kontekst."
)

OUT_OF_SCOPE = (
    "UAMD GPT shërben për informacione të Universitetit 'Aleksandër Moisiu' Durrës. "
    "Mund të pyesësh për fakultete, programe, pranime, orare, kontakt, rregullore, etj. "
    "Për fillim: https://uamd.edu.al/"
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


def wants_pdfs(question: str) -> bool:
    q = question.lower()
    return any(
        k in q
        for k in (
            "pdf", "dokument", "rregullore", "statut", "vendim", "udhëzim", "udhezim",
            "program", "programe", "kuota", "excel", "tabel", "tarif", "orar",
        )
    )


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


def _keyword_score(question: str, text: str) -> float:
    q_tokens = [t for t in re.findall(r"[a-zçë0-9]{3,}", question.lower()) if t not in {"the", "and", "per", "nga", "nje", "një"}]
    if not q_tokens:
        return 0.0
    hay = text.lower()
    hits = sum(1 for t in q_tokens if t in hay)
    return hits / max(len(q_tokens), 1)


class RAGEngine:
    def __init__(self) -> None:
        self._embedding_model = None
        self._embedding_backend = EMBEDDING_BACKEND
        self._openai = None
        self._ready = False
        self._query_cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl = int(os.getenv("QUERY_CACHE_TTL", "600"))
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

    def _semantic_rerank(self, question: str, chunks: list[dict[str, Any]], top_k: int = TOP_K) -> list[dict[str, Any]]:
        if not chunks:
            return []
        q_vec = self._embed([question])[0]
        doc_vecs = self._embed([c["content"] for c in chunks])
        semantic = doc_vecs @ q_vec
        hits: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            kw = _keyword_score(question, chunk["content"] + " " + (chunk.get("title") or ""))
            score = 0.75 * float(semantic[i]) + 0.25 * kw
            item = dict(chunk)
            item["score"] = score
            hits.append(item)
        hits.sort(key=lambda x: x["score"], reverse=True)
        return hits[:top_k]

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
    ) -> str:
        if not contexts and not source_docs:
            return NO_ANSWER

        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key or api_key.startswith("sk-your"):
            raise RuntimeError("Incorrect API key provided: OPENAI_API_KEY is missing or placeholder.")

        self._openai = OpenAI(api_key=api_key)

        pages_block = ""
        docs_for_list = source_docs or []
        if docs_for_list:
            lines = [f"- {d.get('title') or 'Faqe UAMD'}: {d.get('url')}" for d in docs_for_list[:10]]
            pages_block = "Faqet zyrtare të gjetura:\n" + "\n".join(lines) + "\n\n"
        elif search_hits:
            lines = [f"- {h.get('title') or 'UAMD'}: {h.get('url')}" for h in search_hits[:10]]
            pages_block = "Rezultatet e kërkimit:\n" + "\n".join(lines) + "\n\n"

        context_block = "\n\n".join(
            f"[Burimi: {c.get('title') or 'UAMD'}] ({c.get('url')})\n{c.get('content')}"
            for c in contexts
        )

        user_prompt = (
            f"{pages_block}"
            f"Ekstrakte nga burimet zyrtare:\n\n{context_block}\n\n"
            f"Pyetja: {question}\n\n"
            "Udhëzime të detyrueshme:\n"
            "- Jep gjithmonë një përgjigje të dobishme në shqip.\n"
            "- Nxirr sa më shumë fakte relevante nga konteksti.\n"
            "- Nëse mungon një detaj, thuaj çfarë dihet dhe jep linkun më të mirë zyrtar.\n"
            "- MOS përdor frazën 'Nuk gjeta një përgjigje të saktë'.\n"
            "- Maksimumi 6 fjali ose lista e shkurtër."
        )

        response = self._openai.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
            max_tokens=420,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        answer = (response.choices[0].message.content or "").strip()
        if (not answer) or ("nuk gjeta një përgjigje" in answer.lower()):
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

        cache_key = re.sub(r"\s+", " ", question.lower()).strip()
        cached = self._query_cache.get(cache_key)
        if cached and time.time() - cached["ts"] < self._cache_ttl:
            # Never serve stale refusal answers
            if "nuk gjeta një përgjigje" not in (cached.get("answer") or "").lower():
                return {"answer": cached["answer"], "sources": cached["sources"], "cached": True}

        search_hits = search_uamd(question, max_results=max(TOP_K, 12))
        if not search_hits:
            search_hits = [
                {"url": "https://uamd.edu.al/", "title": "UAMD", "snippet": "", "provider": "fallback"}
            ]

        urls = [h["url"] for h in search_hits]
        docs = fetch_many(urls, max_docs=MAX_DOCS, include_pdfs=True)

        if not docs:
            answer = (
                "Po kërkova në faqen zyrtare të UAMD. Mund të fillosh nga këto burime:\n"
                "- https://uamd.edu.al/\n"
                "- https://uamd.edu.al/kendi-i-maturantit/\n"
                "- https://admissions.prime-solutions.al/\n"
                "Kontakt: info@uamd.edu.al"
            )
            return {"answer": answer, "sources": urls[:5]}

        chunks = self._chunk_documents(docs)
        ranked = self._semantic_rerank(question, chunks, top_k=max(TOP_K, 10))
        relevant = ranked[: max(6, min(10, len(ranked)))]

        answer = self._generate(question, relevant, source_docs=docs, search_hits=search_hits)

        sources: list[str] = []
        for c in relevant:
            if c.get("url") and c["url"] not in sources:
                sources.append(c["url"])
        for d in docs:
            if d["url"] not in sources:
                sources.append(d["url"])

        result = {"answer": answer, "sources": sources[:10]}
        if "nuk gjeta një përgjigje" not in answer.lower():
            self._query_cache[cache_key] = {**result, "ts": time.time()}

        print(
            f"[rag] answered in {time.time() - started:.2f}s | docs={len(docs)} chunks={len(chunks)} sources={len(result['sources'])}"
        )
        return result


def get_engine() -> RAGEngine:
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = RAGEngine()
    return _engine
