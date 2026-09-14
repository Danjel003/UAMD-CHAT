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
TOP_K = int(os.getenv("TOP_K", "5"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "600"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "60"))
MAX_CHUNKS_PER_DOC = int(os.getenv("MAX_CHUNKS_PER_DOC", "3"))
MAX_TOTAL_CHUNKS = int(os.getenv("MAX_TOTAL_CHUNKS", "15"))
MIN_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", "0.05"))
MAX_DOCS = int(os.getenv("MAX_DOCS", "5"))
USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "auto").lower()  # auto|always|never


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
    "5) Mos shpik fakte që nuk janë në kontekst.\n"
    "6) Nëse pyetja është për Erasmus/mobilitet, MOS listo programe studimi të fakulteteve; "
    "fokusohu te shkëmbimet, thirrjet, bursa dhe kontaketet e Drejtorisë së Projekteve."
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


class RAGEngine:
    def __init__(self) -> None:
        self._embedding_model = None
        self._embedding_backend = EMBEDDING_BACKEND
        self._openai = None
        self._ready = False
        self._query_cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl = int(os.getenv("QUERY_CACHE_TTL", "1800"))
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
            item = dict(chunk)
            item["kw"] = kw
            item["score"] = kw
            pre.append(item)
        pre.sort(key=lambda x: x["kw"], reverse=True)

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
            chunk["score"] = 0.7 * semantic + 0.3 * float(chunk.get("kw") or 0)
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
        page_limit = 10 if deep_q else 5
        if docs_for_list:
            lines = [f"- {d.get('title') or 'Faqe UAMD'}: {d.get('url')}" for d in docs_for_list[:page_limit]]
            pages_block = "Faqet zyrtare të gjetura:\n" + "\n".join(lines) + "\n\n"
        elif search_hits:
            lines = [f"- {h.get('title') or 'UAMD'}: {h.get('url')}" for h in search_hits[:page_limit]]
            pages_block = "Rezultatet e kërkimit:\n" + "\n".join(lines) + "\n\n"

        ctx_limit = 12 if deep_q else 5
        ctx_chars = 1600 if is_person else (1400 if deep_q else 900)
        context_block = "\n\n".join(
            f"[Burimi: {c.get('title') or 'UAMD'}] ({c.get('url')})\n{(c.get('content') or '')[:ctx_chars]}"
            for c in contexts[:ctx_limit]
        )

        catalog_section = ""
        if catalog_block:
            catalog_section = (
                "LISTA E PLOTË E PROGRAMEVE (nga burimet zyrtare të fakultetit — përdore detyrimisht):\n"
                f"{catalog_block}\n\n"
            )

        extra_rules = ""
        max_tokens = 280
        if is_programs:
            max_tokens = 700
            extra_rules = (
                "- Pyetja kërkon LISTËN E PLOTË të programeve.\n"
                "- Listo TË GJITHA programet: Bachelor, Master Shkencor, Master Profesional "
                "dhe programet profesionale 2-vjeçare.\n"
                "- MOS lër asnjë program jashtë nëse është në listën e plotë ose në kontekst.\n"
                "- Organizoi përgjigjen në seksione sipas ciklit (Bachelor / Master / Profesional).\n"
                "- Nuk vlen limiti i 6 fjalive për këtë pyetje; jep listën e plotë.\n"
            )
        elif is_erasmus:
            max_tokens = 650
            extra_rules = (
                "- Jep informacion SA MË TË PLOTË për Erasmus+ / mobilitetet studentore.\n"
                "- Përmend: ku publikohen thirrjet, çfarë ofrohet (shkëmbime studentore, bursa, ICM), "
                "ku të aplikojnë / kontaktojnë (Drejtoria e Projekteve dhe Marrëdhënieve me Jashtë), "
                "dhe linke zyrtare.\n"
                "- Nëse ke thirrje konkrete, përmend disa shembuj me afate/destinacione.\n"
                "- Nuk vlen limiti i 6 fjalive; jep përmbledhje të plotë.\n"
            )
        elif is_person:
            max_tokens = 550
            who = person_name or "këtij personi"
            extra_rules = (
                f"- Pyetja është për personin/lektorin: {who}.\n"
                "- Nxirr nga konteksti çdo biografi / rol / titull / departament / fakultet që ekziston.\n"
                "- Nëse emri gjendet, jep përmbledhje të plotë të informacionit publik.\n"
                "- Nëse emri NUK gjendet në kontekst, thuaj qartë që nuk u gjet informacion publik "
                "për këtë emër në faqen zyrtare dhe jep linkun e rektoratit/organikës.\n"
                "- Mos invento biografi.\n"
            )

        user_prompt = (
            f"{pages_block}"
            f"{catalog_section}"
            f"Ekstrakte nga burimet zyrtare:\n\n{context_block}\n\n"
            f"Pyetja: {question}\n\n"
            "Udhëzime të detyrueshme:\n"
            "- Jep gjithmonë një përgjigje të dobishme në shqip.\n"
            "- Nxirr sa më shumë fakte relevante nga konteksti.\n"
            "- Nëse mungon një detaj, thuaj çfarë dihet dhe jep linkun më të mirë zyrtar.\n"
            "- MOS përdor frazën 'Nuk gjeta një përgjigje të saktë'.\n"
            "- Për pyetje të zakonshme: maksimumi 6 fjali ose lista e shkurtër.\n"
            f"{extra_rules}"
        )

        response = self._openai.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        answer = (response.choices[0].message.content or "").strip()
        if (not answer) or ("nuk gjeta një përgjigje" in answer.lower()):
            if catalog_block:
                return catalog_block + "\n\nBurime: https://uamd.edu.al/"
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

        search_hits = search_uamd(question, max_results=20 if is_person else (16 if wide else max(TOP_K, 8)))
        if not search_hits:
            search_hits = [
                {"url": "https://uamd.edu.al/", "title": "UAMD", "snippet": "", "provider": "fallback"}
            ]

        urls = [h["url"] for h in search_hits]
        need_pdfs = wants_pdfs(question) or is_programs
        expand = is_programs or is_person or any(
            k in question.lower()
            for k in ("bachelor", "master", "dega", "deget", "fakultet")
        )
        max_docs = 12 if is_person else (10 if wide else MAX_DOCS)
        docs = fetch_many(
            urls,
            max_docs=max_docs,
            include_pdfs=need_pdfs,
            expand_faculty=expand,
        )

        # For person queries, prioritize docs that actually contain the name
        if is_person and person_name and docs:
            name_l = person_name.lower()
            parts = [p for p in name_l.split() if len(p) >= 3]

            def _name_hit(doc: dict[str, Any]) -> int:
                hay = f"{doc.get('title') or ''} {doc.get('text') or ''}".lower()
                if name_l in hay:
                    return 2
                if parts and all(p in hay for p in parts):
                    return 1
                return 0

            docs = sorted(docs, key=_name_hit, reverse=True)

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
            for doc in docs:
                text = doc.get("text") or ""
                # For person search, prefer a window around the name
                if is_person and person_name:
                    low = text.lower()
                    idx = low.find(person_name.lower())
                    if idx < 0:
                        for p in person_name.lower().split():
                            if len(p) >= 3 and p in low:
                                idx = low.find(p)
                                break
                    if idx >= 0:
                        start = max(0, idx - 400)
                        end = min(len(text), idx + 1200)
                        text = text[start:end]
                lead = (
                    f"{doc.get('title') or ''}\n{doc.get('url') or ''}\n"
                    f"{text[:1400]}"
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
                    simple_split(doc.get("text") or "", chunk_size=800, overlap=80)[:5]
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
        answer = self._generate(
            question,
            relevant,
            source_docs=docs,
            search_hits=search_hits,
            catalog_block=catalog_block,
        )

        sources: list[str] = []
        for c in relevant:
            if c.get("url") and c["url"] not in sources:
                sources.append(c["url"])
        for d in docs:
            if d["url"] not in sources:
                sources.append(d["url"])

        result = {"answer": answer, "sources": sources[:12]}
        if "nuk gjeta një përgjigje" not in answer.lower():
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
