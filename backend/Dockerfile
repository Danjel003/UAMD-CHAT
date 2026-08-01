# Lightweight production image for UAMD GPT (OpenAI embeddings — no Torch)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EMBEDDING_BACKEND=openai \
    FLASK_DEBUG=false \
    PORT=10000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY app.py rag_engine.py scraper.py search_engine.py uamd_map.py ./

EXPOSE 10000

CMD gunicorn -b 0.0.0.0:${PORT} -w 1 --threads 4 --timeout 120 app:app
