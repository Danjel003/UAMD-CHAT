"""
UAMD GPT — PDF ingestion pipeline.
Parses PDFs with PyMuPDF, chunks text, embeds, and stores in ChromaDB.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = Path(os.getenv("UPLOAD_FOLDER", BASE_DIR / "uploads"))
CHROMA_PATH = Path(os.getenv("CHROMA_PATH", BASE_DIR / "chroma_db"))
CACHE_FOLDER = Path(os.getenv("CACHE_FOLDER", BASE_DIR / "cache"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))
COLLECTION_NAME = "uamd_documents"

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
CHROMA_PATH.mkdir(parents=True, exist_ok=True)
CACHE_FOLDER.mkdir(parents=True, exist_ok=True)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract clean text from a PDF using PyMuPDF."""
    doc = fitz.open(pdf_path)
    pages: list[str] = []
    try:
        for page in doc:
            text = page.get_text("text")
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            pages.append(text.strip())
    finally:
        doc.close()
    return "\n\n".join(p for p in pages if p)


def split_into_chunks(text: str, source: str) -> list[dict[str, Any]]:
    """Split text into overlapping character chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""],
    )
    pieces = splitter.split_text(text)
    chunks: list[dict[str, Any]] = []
    for i, content in enumerate(pieces):
        content = content.strip()
        if len(content) < 40:
            continue
        chunks.append(
            {
                "id": f"{source}::{i}",
                "content": content,
                "metadata": {
                    "source": source,
                    "chunk_index": i,
                },
            }
        )
    return chunks


def get_embedding_model():
    """Load embedding model with Qwen3 primary and BGE-M3 fallback."""
    from sentence_transformers import SentenceTransformer

    primary = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-4B")
    fallback = os.getenv("EMBEDDING_FALLBACK", "BAAI/bge-m3")

    cache_dir = str(CACHE_FOLDER / "embeddings")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    try:
        print(f"[ingest] Loading embedding model: {primary}")
        model = SentenceTransformer(primary, cache_folder=cache_dir, trust_remote_code=True)
        print(f"[ingest] Using embedding model: {primary}")
        return model, primary
    except Exception as exc:
        print(f"[ingest] Primary model failed ({exc}). Falling back to {fallback}")
        model = SentenceTransformer(fallback, cache_folder=cache_dir, trust_remote_code=True)
        print(f"[ingest] Using embedding model: {fallback}")
        return model, fallback


def get_chroma_collection(embedding_dim: int | None = None):
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=str(CHROMA_PATH),
        settings=Settings(anonymized_telemetry=False, allow_reset=True),
    )
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def load_ingest_manifest() -> dict[str, Any]:
    manifest_path = CACHE_FOLDER / "ingest_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"files": {}}


def save_ingest_manifest(manifest: dict[str, Any]) -> None:
    manifest_path = CACHE_FOLDER / "ingest_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def ingest_pdf(pdf_path: Path, embedding_model=None) -> dict[str, Any]:
    """Ingest a single PDF into ChromaDB. Skips if already indexed with same hash."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    source = pdf_path.name
    digest = file_hash(pdf_path)
    manifest = load_ingest_manifest()

    if manifest.get("files", {}).get(source, {}).get("hash") == digest:
        return {
            "source": source,
            "status": "skipped",
            "reason": "already_indexed",
            "chunks": manifest["files"][source].get("chunks", 0),
        }

    if embedding_model is None:
        embedding_model, _ = get_embedding_model()

    text = extract_text_from_pdf(pdf_path)
    if not text.strip():
        return {"source": source, "status": "error", "reason": "empty_pdf", "chunks": 0}

    chunks = split_into_chunks(text, source)
    if not chunks:
        return {"source": source, "status": "error", "reason": "no_chunks", "chunks": 0}

    collection = get_chroma_collection()

    # Remove previous chunks for this source if re-ingesting
    try:
        existing = collection.get(where={"source": source})
        if existing and existing.get("ids"):
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    ids = [c["id"] for c in chunks]
    documents = [c["content"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]

    embeddings = embedding_model.encode(
        documents,
        batch_size=16,
        show_progress_bar=False,
        normalize_embeddings=True,
    ).tolist()

    # Chroma has a batch size limit; insert in batches
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i : i + batch_size],
            documents=documents[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
            embeddings=embeddings[i : i + batch_size],
        )

    manifest.setdefault("files", {})[source] = {
        "hash": digest,
        "chunks": len(chunks),
        "path": str(pdf_path),
    }
    save_ingest_manifest(manifest)

    # Invalidate BM25 cache so rag_engine rebuilds it
    bm25_cache = CACHE_FOLDER / "bm25_corpus.json"
    if bm25_cache.exists():
        bm25_cache.unlink()

    return {"source": source, "status": "indexed", "chunks": len(chunks)}


def ingest_directory(directory: Path | None = None) -> list[dict[str, Any]]:
    """Ingest all PDFs from the uploads folder."""
    directory = Path(directory or UPLOAD_FOLDER)
    pdfs = sorted(directory.glob("*.pdf"))
    if not pdfs:
        print("[ingest] No PDF files found.")
        return []

    embedding_model, model_name = get_embedding_model()
    results: list[dict[str, Any]] = []
    for pdf in pdfs:
        print(f"[ingest] Processing: {pdf.name}")
        result = ingest_pdf(pdf, embedding_model=embedding_model)
        result["embedding_model"] = model_name
        results.append(result)
        print(f"[ingest] {result}")
    return results


if __name__ == "__main__":
    print("=== UAMD GPT Ingestion ===")
    results = ingest_directory()
    total = sum(r.get("chunks", 0) for r in results if r.get("status") == "indexed")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    print(f"Done. Indexed chunks: {total}. Skipped files: {skipped}.")
