"""
UAMD GPT — Flask API
Live answers from uamd.edu.al only.
Endpoints: POST /ask, GET /health

Copyright (c) 2026 Danjel Kalari. All rights reserved.
Author: Danjel Kalari
Product of: Drejtoria e IT / Sektori i Inovacionit dhe Software
Universiteti "Aleksandër Moisiu" Durrës
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "False")

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from rag_engine import get_engine

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)

# In production set FRONTEND_ORIGIN=https://your-app.vercel.app
_frontend = os.getenv("FRONTEND_ORIGIN", "*").strip()
CORS(
    app,
    resources={r"/*": {"origins": _frontend if _frontend else "*"}},
)


@app.get("/health")
def health():
    engine = get_engine()
    tavily = bool(os.getenv("TAVILY_API_KEY") and not os.getenv("TAVILY_API_KEY", "").startswith("tvly-your"))
    serp = bool(os.getenv("SERPAPI_API_KEY") and not os.getenv("SERPAPI_API_KEY", "").startswith("your-"))
    openai_ok = bool(
        os.getenv("OPENAI_API_KEY") and not os.getenv("OPENAI_API_KEY", "").startswith("sk-your")
    )
    return jsonify(
        {
            "status": "ok",
            "service": "UAMD GPT",
            "domain": "uamd.edu.al",
            "ready": engine._ready,
            "embedding_backend": os.getenv("EMBEDDING_BACKEND", "local"),
            "openai_configured": openai_ok,
            "tavily_configured": tavily,
            "serpapi_configured": serp,
            "search_fallback": "duckduckgo" if not (tavily or serp) else None,
        }
    )


@app.post("/ask")
def ask():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or data.get("query") or "").strip()

    if not question:
        return jsonify({"error": "Field 'question' is required."}), 400

    try:
        engine = get_engine()
        if not engine._ready:
            engine.initialize()
        result = engine.ask(question)
        return jsonify(result)
    except Exception as exc:
        print(f"[app] /ask error: {exc}")
        msg = str(exc).lower()
        if "api key" in msg or "authentication" in msg or ("401" in msg and "incorrect" in msg):
            return jsonify(
                {
                    "answer": (
                        "Çelësi OpenAI (OPENAI_API_KEY) nuk është konfiguruar saktë. "
                        "Vendoseni në backend/.env dhe ristartoni serverin."
                    ),
                    "sources": [],
                    "error": str(exc),
                }
            ), 401
        if "429" in msg or "quota" in msg or "credit" in msg or "insufficient" in msg or "billing" in msg:
            return jsonify(
                {
                    "answer": (
                        "Llogaria OpenAI nuk ka kredi të mjaftueshme. "
                        "Shto kredi te https://platform.openai.com/account/billing dhe provo përsëri."
                    ),
                    "sources": [],
                    "error": str(exc),
                }
            ), 429
        return jsonify(
            {
                "answer": (
                    "Ndodhi një gabim teknik gjatë kërkimit. "
                    "Provo përsëri, ose vizito https://uamd.edu.al/ / kontakto info@uamd.edu.al."
                ),
                "sources": ["https://uamd.edu.al/"],
                "error": str(exc),
            }
        ), 500


def warm_up():
    if not os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "").startswith("sk-your"):
        print("[app] WARNING: OPENAI_API_KEY not configured.")
    if not os.getenv("TAVILY_API_KEY") and not os.getenv("SERPAPI_API_KEY"):
        print("[app] INFO: No Tavily/SerpAPI key — using DuckDuckGo site:uamd.edu.al fallback.")
    try:
        get_engine().initialize()
    except Exception as exc:
        print(f"[app] Warm-up deferred: {exc}")


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5001"))
    debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    threading.Thread(target=warm_up, daemon=True).start()
    print(f"[app] UAMD GPT backend → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
