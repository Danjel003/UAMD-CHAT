"""
UAMD GPT — Fast live RAG over uamd.edu.al.
Search → parallel scrape → in-memory semantic rank → GPT-4o-mini.
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
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "local").lower()  # local | openai
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
TOP_K = int(os.getenv("TOP_K", "5"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))
MAX_CHUNKS_PER_DOC = int(os.getenv("MAX_CHUNKS_PER_DOC", "4"))
MAX_TOTAL_CHUNKS = int(os.getenv("MAX_TOTAL_CHUNKS", "16"))
MIN_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", "0.12"))

NO_ANSWER = (
    "Nuk gjeta një përgjigje të saktë në faqen zyrtare të Universitetit "
    "'Aleksandër Moisiu' Durrës. Ju lutem kontaktoni universitetin për informacion zyrtar."
)

SYSTEM_PROMPT = (
    "Ti je UAMD GPT, asistenti zyrtar informues i Universitetit 'Aleksandër Moisiu' Durrës. "
    "Përgjigju duke përdorur informacionin nga konteksti i faqeve zyrtare. "
    "Jep përgjigje konkrete, të shkurtra dhe të dobishme. "
    "Nëse konteksti ka informacion të pjesshëm, jep atë që dihet qartë (p.sh. vendndodhja Durrës, "
    "lista e fakulteteve, email-i info@uamd.edu.al, linku i Admissions) dhe shto linkun zyrtar. "
    "Mos thuaj 'nuk gjeta' nëse konteksti përmban fakte të dobishme. "
    "Mos shpik të dhëna që nuk janë në kontekst."
)

OUT_OF_SCOPE = (
    "UAMD GPT shërben vetëm për informacione zyrtare të Universitetit "
    "'Aleksandër Moisiu' Durrës (uamd.edu.al). Ju lutem bëni një pyetje që lidhet "
    "me universitetin, programet, pranimet, rregulloret ose shërbimet e tij."
)

_lock = threading.Lock()
_engine: "RAGEngine | None" = None


def looks_out_of_scope(question: str) -> bool:
    q = question.lower().strip()
    if len(q) < 2:
        return True

    signals = [
        "uamd", "universitet", "fakultet", "student", "master", "bachelor",
        "bakalaureat", "program", "kurs", "lënd", "lend", "provim", "regjistr",
        "pranim", "aplikim", "tarif", "burs", "diplom", "semest", "bibliotek",
        "kampus", "durrës", "durres", "moisiu", "aleksandër", "aleksander",
        "rregullore", "statut", "pedagog", "profesor", "sekretari", "kontak",
        "afat", "kredit", "ects", "dega", "orari", "viti akademik", "kuota",
        "transfer", "dekan", "doktoratur", "praktik", "dokument", "pdf",
    ]
    if any(s in q for s in signals):
        return False

    off = [
        "si je", "hello", "hi ", "moti", "football", "futboll", "bitcoin",
        "recetë", "recete", "shaka", "joke", "chatgpt", "poezi", "politikë",
    ]
    if any(p in q for p in off):
        return True

    return bool(re.search(r"\b(kryeqyteti i|who was|how to cook|shkruaj kod)\b", q))


def wants_pdfs(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in ("pdf", "dokument", "rregullore", "statut", "vendim", "udhëzim", "udhezim"))


def simple_split(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Lightweight splitter (no LangChain dependency — better for cloud hosting)."""
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
        # Prefer breaking on paragraph/sentence
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


class RAGEngine:
    def __init__(self) -> None:
        self._embedding_model = None
        self._embedding_backend = EMBEDDING_BACKEND
        self._openai = None
        self._ready = False
        self._query_cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl = int(os.getenv("QUERY_CACHE_TTL", "900"))
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
                # tiny warm-up call skipped to save tokens; first request warms naturally
            else:
                print("[rag] Loading local embedding model BAAI/bge-m3...")
                from sentence_transformers import SentenceTransformer

                cache_dir = str(CACHE_FOLDER / "embeddings")
                Path(cache_dir).mkdir(parents=True, exist_ok=True)
                self._embedding_model = SentenceTransformer(
                    EMBEDDING_MODEL,
                    cache_folder=cache_dir,
                    trust_remote_code=True,
                )
                self._embedding_model.encode(["uamd warmup"], normalize_embeddings=True)

            self._ready = True
            print(f"[rag] Ready (backend={self._embedding_backend}).")

    def _chunk_documents(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for doc in docs:
            lead = f"{doc.get('title') or ''}\n{doc.get('url') or ''}\n{(doc.get('text') or '')[:500]}".strip()
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
                if len(content) < 50:
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
        # OpenAI embedding API accepts batches; keep batches modest
        out: list[list[float]] = []
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = self._openai.embeddings.create(
                model=OPENAI_EMBEDDING_MODEL,
                input=batch,
            )
            # Ensure order by index
            sorted_data = sorted(resp.data, key=lambda x: x.index)
            for row in sorted_data:
                vec = np.asarray(row.embedding, dtype=np.float32)
                norm = np.linalg.norm(vec) + 1e-12
                out.append((vec / norm).tolist())
        return np.asarray(out, dtype=np.float32)

    def _embed(self, texts: list[str]) -> np.ndarray:
        """Embed texts with small hash cache for repeated chunks."""
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
                    missing_texts,
                    batch_size=32,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                )
            with self._embed_cache_lock:
                for i, vec in zip(missing_idx, encoded):
                    arr = np.asarray(vec, dtype=np.float32)
                    vectors[i] = arr
                    self._embed_cache[content_hash(texts[i])] = arr
                    if len(self._embed_cache) > 4000:
                        for k in list(self._embed_cache.keys())[:800]:
                            self._embed_cache.pop(k, None)

        return np.vstack(vectors)

    def _semantic_rerank(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        top_k: int = TOP_K,
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []

        q_vec = self._embed([question])[0]
        doc_vecs = self._embed([c["content"] for c in chunks])
        # Cosine similarity since vectors are normalized → dot product
        scores = doc_vecs @ q_vec

        ranked_idx = np.argsort(-scores)[:top_k]
        hits: list[dict[str, Any]] = []
        for i in ranked_idx:
            item = dict(chunks[int(i)])
            item["score"] = float(scores[int(i)])
            hits.append(item)
        return hits

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
            raise RuntimeError(
                "Incorrect API key provided: OPENAI_API_KEY is missing or placeholder."
            )

        # Keep client key in sync if .env changed without full process issues
        self._openai = OpenAI(api_key=api_key)

        pages_block = ""
        docs_for_list = source_docs or []
        if docs_for_list:
            lines = [f"- {d.get('title') or 'Faqe UAMD'}: {d.get('url')}" for d in docs_for_list]
            pages_block = "Faqet zyrtare të gjetura:\n" + "\n".join(lines) + "\n\n"
        elif search_hits:
            lines = [f"- {h.get('title') or 'UAMD'}: {h.get('url')}" for h in search_hits]
            pages_block = "Rezultatet e kërkimit në uamd.edu.al:\n" + "\n".join(lines) + "\n\n"

        context_block = "\n\n".join(
            f"[Burimi: {c.get('title') or 'UAMD'}] ({c.get('url')})\n{c.get('content')}"
            for c in contexts
        )

        user_prompt = (
            f"{pages_block}"
            f"Ekstrakte nga burimet zyrtare të UAMD:\n\n{context_block}\n\n"
            f"Pyetja: {question}\n\n"
            "Udhëzime:\n"
            "- Përgjigju me fakte nga konteksti/titujt/linket më sipër.\n"
            "- Jep përgjigje konkrete (lista, email, linku i aplikimit, etj.) kur janë të disponueshme.\n"
            "- Nëse informacioni është i pjesshëm, jep pjesën e saktë + ku të vazhdohet (link zyrtar).\n"
            "- Përgjigje e shkurtër (maks. 5 fjali ose bullets).\n"
            f"- Vetëm nëse konteksti është plotësisht i parëndësishëm: {NO_ANSWER}"
        )

        response = self._openai.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
            max_tokens=350,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        answer = (response.choices[0].message.content or "").strip()
        return answer or NO_ANSWER

    def ask(self, question: str) -> dict[str, Any]:
        started = time.time()
        if not self._ready:
            self.initialize()

        question = (question or "").strip()
        if not question:
            return {"answer": "Ju lutem shkruani një pyetje.", "sources": []}

        if looks_out_of_scope(question):
            return {"answer": OUT_OF_SCOPE, "sources": []}

        cache_key = re.sub(r"\s+", " ", question.lower()).strip()
        cached = self._query_cache.get(cache_key)
        if cached and time.time() - cached["ts"] < self._cache_ttl:
            # Never serve stale hard failures forever if they were NO_ANSWER without sources
            if cached["answer"] != NO_ANSWER or cached.get("sources"):
                return {"answer": cached["answer"], "sources": cached["sources"], "cached": True}

        # 1) Search only within uamd.edu.al
        search_hits = search_uamd(question, max_results=TOP_K)
        if not search_hits:
            return {"answer": NO_ANSWER, "sources": []}

        urls = [h["url"] for h in search_hits]

        # 2) Parallel scrape (PDF enrichment only when needed)
        docs = fetch_many(urls, max_docs=TOP_K, include_pdfs=wants_pdfs(question))
        if not docs:
            # Still allow title-only answer path from search hits when useful
            title_contexts = [
                {
                    "title": h.get("title") or "UAMD",
                    "url": h["url"],
                    "content": f"{h.get('title') or ''}\n{h.get('snippet') or ''}".strip(),
                    "score": 1.0,
                }
                for h in search_hits
                if (h.get("title") or h.get("snippet"))
            ]
            if not title_contexts:
                return {"answer": NO_ANSWER, "sources": urls}
            answer = self._generate(question, title_contexts, search_hits=search_hits)
            return {"answer": answer, "sources": urls}

        # 3) Chunk + in-memory semantic re-rank (no Chroma write per query)
        chunks = self._chunk_documents(docs)
        ranked = self._semantic_rerank(question, chunks, top_k=TOP_K)
        relevant = [c for c in ranked if c.get("score", 0) >= MIN_SCORE] or ranked[: min(3, len(ranked))]

        if not relevant:
            return {"answer": NO_ANSWER, "sources": [d["url"] for d in docs]}

        # 4) Generate
        answer = self._generate(question, relevant, source_docs=docs, search_hits=search_hits)

        sources: list[str] = []
        for c in relevant:
            if c.get("url") and c["url"] not in sources:
                sources.append(c["url"])
        for d in docs:
            if d["url"] not in sources:
                sources.append(d["url"])

        result = {"answer": answer, "sources": sources[:TOP_K]}
        # Cache successful answers (and useful NO_ANSWER with sources) briefly
        if answer != NO_ANSWER:
            self._query_cache[cache_key] = {**result, "ts": time.time()}

        elapsed = time.time() - started
        print(f"[rag] answered in {elapsed:.2f}s | sources={len(result['sources'])}")
        return result


def get_engine() -> RAGEngine:
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = RAGEngine()
    return _engine
