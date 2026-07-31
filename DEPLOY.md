# Si ta hostosh UAMD GPT (për fillestarë)

Do të publikojmë chatbot-in online me **2 shërbime falas**:

1. **Render** → backend (Python)
2. **Vercel** → frontend (React)

Kohë e përafërt: 30–45 minuta.

---

## PARA SE TË FILLOSH

Hap llogari (falas) në:

1. [GitHub](https://github.com/signup)
2. [Render](https://render.com)
3. [Vercel](https://vercel.com)

Duhet të kesh edhe `OPENAI_API_KEY` (atë që e përdor tashmë lokalisht).

---

## HAP 1 — Ngarko kodin në GitHub

### 1.1 Krijo repository

1. Shko te https://github.com/new  
2. Repository name: `UAMD-CHAT`  
3. Public  
4. **Mos** hidh check te “Add README”  
5. Kliko **Create repository**

### 1.2 Ngarko projektin nga kompjuteri

Në Terminal (Mac), ekzekuto:

```bash
cd /Users/danjelkalari/Desktop/UAMD-CHAT
git add .
git commit -m "UAMD GPT ready for hosting"
git branch -M main
git remote add origin https://github.com/EMRI-YT-GITHUB/UAMD-CHAT.git
git push -u origin main
```

> Zëvendëso `EMRI-YT-GITHUB` me emrin tënd të GitHub.

**E rëndësishme:** mos e ngarko `.env` (është në `.gitignore`). Çelësat i vendosim më vonë te Render/Vercel.

---

## HAP 2 — Host backend-in në Render

1. Hyr në https://dashboard.render.com  
2. **New +** → **Web Service**  
3. Lidh GitHub dhe zgjidh repo `UAMD-CHAT`  
4. Settings:

| Fusha | Vlera |
|------|--------|
| Name | `uamd-gpt-backend` |
| Root Directory | `backend` |
| Runtime | **Docker** |
| Instance type | **Free** |

5. Te **Environment** shto:

| Key | Value |
|-----|--------|
| `OPENAI_API_KEY` | `sk-proj-...` (çelësi yt) |
| `EMBEDDING_BACKEND` | `openai` |
| `FLASK_DEBUG` | `false` |

6. Kliko **Create Web Service**  
7. Prit 5–10 minuta derisa statusi të bëhet **Live**  
8. Kopjo URL-në, p.sh.:

`https://uamd-gpt-backend.onrender.com`

9. Testo në browser:

`https://uamd-gpt-backend.onrender.com/health`

Duhet të shohësh `"status": "ok"`.

> **Shënim:** në planin Free, Render “fle” pas ~15 min pa aktivitet. Pyetja e parë pas gjumit mund të zgjasë 30–60 sekonda.

---

## HAP 3 — Host frontend-in në Vercel

1. Hyr në https://vercel.com  
2. **Add New…** → **Project**  
3. Importo `UAMD-CHAT` nga GitHub  
4. Settings:

| Fusha | Vlera |
|------|--------|
| Framework Preset | Vite |
| Root Directory | `frontend` |
| Build Command | `npm run build` |
| Output Directory | `dist` |

5. Te **Environment Variables** shto:

| Key | Value |
|-----|--------|
| `VITE_API_URL` | `https://uamd-gpt-backend.onrender.com` |

(pa `/` në fund)

6. Kliko **Deploy**  
7. Kur mbaron, hap linkun e Vercel, p.sh.:

`https://uamd-chat.vercel.app`

---

## HAP 4 — Lidh CORS (opsionale por e rekomanduar)

Kthehu te Render → backend → Environment → shto:

| Key | Value |
|-----|--------|
| `FRONTEND_ORIGIN` | `https://uamd-chat.vercel.app` |

Pastaj **Manual Deploy** → **Deploy latest commit**.

---

## HAP 5 — Testimi final

1. Hap faqen Vercel  
2. Shkruaj: `Cilat fakultete ka UAMD?`  
3. Duhet të marrësh përgjigje + burime nga `uamd.edu.al`

Nëse dështon:

- Kontrollo `/health` te Render  
- Kontrollo që `VITE_API_URL` është i saktë  
- Shiko Logs te Render (gabime OpenAI / kredi)

---

## Kosto

| Shërbimi | Kosto |
|----------|------|
| GitHub | Falas |
| Vercel | Falas |
| Render Free | Falas (me “gjumë”) |
| OpenAI | Sipas përdorimit (`gpt-4o-mini` është i lirë) |

Nëse do që të mos flejë kurrë: Render **Starter** (~7 USD/muaj).

---

## Përditësimet e ardhshme

Sa herë ndryshon kodin lokalisht:

```bash
cd /Users/danjelkalari/Desktop/UAMD-CHAT
git add .
git commit -m "update"
git push
```

Render dhe Vercel e publikojnë automatikisht.
