import { useEffect, useRef, useState } from 'react'
import { Search, ExternalLink, ShieldCheck, Sparkles, Globe } from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_URL || ''
const MIN_LOADING_MS = 400

function UniversityMark({ className = '' }) {
  return (
    <div className={`relative ${className}`}>
      <div className="absolute inset-0 rounded-full bg-white/20 blur-2xl animate-pulse-ring" />
      <img
        src="/Logo_e_Universitetit__Aleksander_Moisiu_.png"
        alt='Logo e Universitetit "Aleksandër Moisiu" Durrës'
        className="relative h-28 w-28 object-contain drop-shadow-2xl animate-float-soft sm:h-32 sm:w-32"
        width={128}
        height={128}
      />
    </div>
  )
}

function LoadingState() {
  return (
    <div className="mt-6 flex items-center gap-4 rounded-2xl border border-white/10 bg-white/5 px-5 py-4 text-white backdrop-blur-sm animate-fade-in-up">
      <div className="spinner shrink-0" />
      <p className="text-sm font-medium tracking-wide text-white/90 sm:text-base">
        Duke kërkuar në faqen zyrtare të UAMD...
      </p>
    </div>
  )
}

function prettyUrl(url) {
  try {
    const u = new URL(url)
    const path = u.pathname.length > 48 ? `${u.pathname.slice(0, 45)}…` : u.pathname
    return `${u.hostname}${path === '/' ? '' : path}`
  } catch {
    return url
  }
}

function AnswerCard({ answer, sources }) {
  return (
    <div className="mt-6 animate-fade-in-up rounded-2xl border border-uamd-100 bg-white p-6 shadow-[0_20px_60px_-20px_rgba(6,20,40,0.45)] sm:p-8">
      <div className="mb-4 flex items-center gap-2">
        <Sparkles className="h-5 w-5 text-uamd-600" />
        <h2 className="font-display text-xl font-semibold text-uamd-900">Përgjigjja</h2>
      </div>

      <div className="answer-prose">{answer}</div>

      {sources?.length > 0 && (
        <div className="mt-7 border-t border-uamd-100 pt-5">
          <div className="mb-3 flex items-center gap-2">
            <Globe className="h-4 w-4 text-uamd-600" />
            <h3 className="text-sm font-semibold tracking-wide text-uamd-800">
              Burimet zyrtare
            </h3>
          </div>
          <ul className="space-y-2">
            {sources.map((src) => (
              <li key={src}>
                <a
                  href={src}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-start gap-2 rounded-xl border border-uamd-50 bg-uamd-50/70 px-3 py-2.5 text-sm text-uamd-700 transition hover:border-uamd-200 hover:bg-white"
                >
                  <ExternalLink className="mt-0.5 h-4 w-4 shrink-0 text-uamd-500 group-hover:text-uamd-700" />
                  <span className="break-all underline-offset-2 group-hover:underline">
                    {prettyUrl(src)}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-uamd-100 bg-uamd-50 px-3 py-1.5 text-xs font-semibold tracking-wide text-uamd-700">
        <ShieldCheck className="h-3.5 w-3.5" />
        Bazuar vetëm në uamd.edu.al
      </div>
    </div>
  )
}

export default function App() {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [answer, setAnswer] = useState(null)
  const [sources, setSources] = useState([])
  const [error, setError] = useState(null)
  const textareaRef = useRef(null)
  const answerRef = useRef(null)

  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  // Scroll to answer only once when a new reply arrives — not on every keystroke
  useEffect(() => {
    if (!answer || loading) return
    answerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [answer, loading])

  async function askQuestion() {
    const q = question.trim()
    if (!q || loading) return

    setLoading(true)
    setError(null)
    setAnswer(null)
    setSources([])

    const started = Date.now()

    try {
      const res = await fetch(`${API_BASE}/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      })

      const data = await res.json()
      const elapsed = Date.now() - started
      const wait = Math.max(0, MIN_LOADING_MS - elapsed)
      if (wait > 0) await new Promise((r) => setTimeout(r, wait))

      if (!res.ok && !data.answer) {
        throw new Error(data.error || 'Kërkesa dështoi')
      }

      setAnswer(data.answer)
      setSources(data.sources || [])
    } catch (err) {
      const elapsed = Date.now() - started
      const wait = Math.max(0, MIN_LOADING_MS - elapsed)
      if (wait > 0) await new Promise((r) => setTimeout(r, wait))
      setError(err.message || 'Ndodhi një gabim. Provoni përsëri.')
    } finally {
      setLoading(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      askQuestion()
    }
  }

  return (
    <div className="bg-mesh relative min-h-screen overflow-x-hidden">
      <div className="grid-overlay pointer-events-none absolute inset-0" />

      <div className="relative z-10 mx-auto flex min-h-screen max-w-3xl flex-col px-4 py-10 sm:px-6 sm:py-14">
        <header className="mb-10 flex flex-col items-center text-center">
          <UniversityMark className="mb-6" />

          <h1 className="font-display text-4xl font-bold tracking-tight text-white sm:text-5xl md:text-6xl">
            UAMD GPT
          </h1>
          <p className="mt-3 max-w-md text-sm leading-relaxed text-white/70 sm:text-base">
            Chatbot për Universitetin “Aleksandër Moisiu” Durrës
          </p>
          <p className="mt-2 text-xs text-white/40">
            Vizitoni faqen zyrtare uamd.edu.al
          </p>
        </header>

        <main className="flex-1">
          <section className="rounded-3xl border border-white/10 bg-white/95 p-5 shadow-[0_30px_80px_-30px_rgba(0,0,0,0.55)] backdrop-blur-xl sm:p-8">
            <label htmlFor="question" className="sr-only">
              Pyetja
            </label>
            <textarea
              id="question"
              ref={textareaRef}
              rows={4}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Shkruaj pyetjen tënde këtu..."
              disabled={loading}
              className="w-full resize-none rounded-2xl border border-uamd-100 bg-uamd-50/60 px-4 py-4 text-base text-uamd-950 outline-none transition placeholder:text-uamd-700/40 focus:border-uamd-500 focus:bg-white focus:ring-4 focus:ring-uamd-500/15 disabled:opacity-70"
            />

            <button
              type="button"
              onClick={askQuestion}
              disabled={loading || !question.trim()}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl bg-uamd-700 px-6 py-4 text-base font-semibold text-white shadow-lg shadow-uamd-900/25 transition hover:bg-uamd-600 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Search className="h-5 w-5" />
              Kërko përgjigjen
            </button>

            <p className="mt-3 text-center text-xs text-uamd-700/50">
              Enter për dërgim · Shift+Enter për rresht të ri
            </p>
          </section>

          {loading && <LoadingState />}

          {error && !loading && (
            <div className="mt-6 animate-fade-in-up rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-800">
              {error}
            </div>
          )}

          {answer && !loading && (
            <div ref={answerRef}>
              <AnswerCard answer={answer} sources={sources} />
            </div>
          )}
        </main>

        <footer className="mt-12 text-center text-xs text-white/35">
          © {new Date().getFullYear()} Universiteti “Aleksandër Moisiu” Durrës · UAMD GPT
        </footer>
      </div>
    </div>
  )
}
