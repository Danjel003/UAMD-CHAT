# UAMD GPT

Chatbot profesional për Universitetin “Aleksandër Moisiu” Durrës.  
Kërkon **vetëm** brenda faqes zyrtare [uamd.edu.al](https://uamd.edu.al) dhe PDF-ve të këtij domain-i.  
**Nuk** përdor njohuri të përgjithshme të internetit.

## Stack

| Shtresa | Teknologjia |
|---------|-------------|
| Frontend | React + Vite + Tailwind CSS |
| Backend | Python Flask |
| Search | Tavily / SerpAPI (`site:uamd.edu.al`) + DuckDuckGo fallback |
| Scraping | BeautifulSoup4 + requests |
| PDF | PyMuPDF |
| Embeddings | BAAI/bge-m3 |
| Vector DB | ChromaDB |
| LLM | OpenAI GPT-4o-mini |

## Si funksionon

1. Kërkon në web me `site:uamd.edu.al` (max 5 rezultate)  
2. Shkarkon faqet HTML dhe PDF-të e domain-it  
3. I ndan në chunks, krijon embeddings (bge-m3)  
4. Bën semantic re-ranking  
5. GPT-4o-mini përgjigjet **vetëm** nga konteksti  
6. Shfaq seksionin **Burimet zyrtare** me linket

Nëse informacioni nuk gjendet:

> Nuk gjeta një përgjigje të saktë në faqen zyrtare të Universitetit ‘Aleksandër Moisiu’ Durrës. Ju lutem kontaktoni universitetin për informacion zyrtar.

## Struktura

```
UAMD-CHAT/
├── backend/
│   ├── app.py
│   ├── search_engine.py
│   ├── scraper.py
│   ├── rag_engine.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
└── README.md
```

## 1. Instalimi i backend-it

> Rekomandohet **Python 3.11**.

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Në `backend/.env` vendos:

```env
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...            # opsionale por e rekomanduar
# ose
SERPAPI_API_KEY=...
```

Pa Tavily/SerpAPI, sistemi përdor automatikisht DuckDuckGo me `site:uamd.edu.al`.

## 2. Instalimi i frontend-it

```bash
cd frontend
npm install
```

## 3. Nisja

Terminal 1 — backend:

```bash
cd backend
source .venv/bin/activate
python app.py
```

→ http://localhost:5001

Terminal 2 — frontend:

```bash
cd frontend
npm run dev
```

→ http://localhost:5173

> Në macOS, porti `5000` shpesh zëhet nga AirPlay. Prandaj default është `5001`.

Ose: `./start.sh`

## API

| Method | Endpoint | Body / përgjigje |
|--------|----------|------------------|
| `GET` | `/health` | Statusi i shërbimit |
| `POST` | `/ask` | `{ "question": "..." }` → `{ "answer": "...", "sources": ["https://uamd.edu.al/..."] }` |

## Shënime

- Pa limit pyetjesh / pa rate limit lokal  
- Cache e shkurtër e pyetjeve (`QUERY_CACHE_TTL`) për shpejtësi  
- Frontend pret minimumi 2s loading, pastaj fade-in  
- Domain i lejuar: vetëm `uamd.edu.al` (dhe `www`)  
