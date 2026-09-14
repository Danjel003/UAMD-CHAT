/*
 * UAMD GPT — Chatbot for Universiteti "Aleksandër Moisiu" Durrës
 * Copyright (c) 2026 Danjel Kalari. All rights reserved.
 * Author: Danjel Kalari
 * Product of: Drejtoria e IT / Sektori i Inovacionit dhe Software
 */

import { useEffect, useRef, useState } from 'react'
import {
  Search,
  ExternalLink,
  ShieldCheck,
  Sparkles,
  Globe,
  X,
  AlertTriangle,
  Info,
} from 'lucide-react'
import { LEGAL_PAGES, FOOTER_LINKS } from './legalContent'

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

function renderInline(text) {
  const parts = []
  const re = /(\*\*[^*]+\*\*|https?:\/\/[^\s)]+)/g
  let last = 0
  let m
  let key = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const token = m[0]
    if (token.startsWith('**')) {
      parts.push(
        <strong key={key++} className="font-semibold text-uamd-900">
          {token.slice(2, -2)}
        </strong>,
      )
    } else {
      parts.push(
        <a
          key={key++}
          href={token}
          target="_blank"
          rel="noopener noreferrer"
          className="text-uamd-600 underline underline-offset-2"
        >
          {token}
        </a>,
      )
    }
    last = m.index + token.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function LegalBody({ markdown }) {
  const lines = markdown.split('\n')
  const blocks = []
  let listItems = []

  function flushList() {
    if (!listItems.length) return
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="mb-4 list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-uamd-800">
        {listItems.map((item, i) => (
          <li key={i}>{renderInline(item)}</li>
        ))}
      </ul>,
    )
    listItems = []
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    if (!trimmed) {
      flushList()
      continue
    }
    if (trimmed.startsWith('## ')) {
      flushList()
      blocks.push(
        <h3 key={`h-${i}`} className="mb-2 mt-6 font-display text-lg font-semibold text-uamd-900 first:mt-0">
          {trimmed.slice(3)}
        </h3>,
      )
      continue
    }
    if (trimmed.startsWith('### ')) {
      flushList()
      blocks.push(
        <h4 key={`h4-${i}`} className="mb-2 mt-4 text-base font-semibold text-uamd-800">
          {trimmed.slice(4)}
        </h4>,
      )
      continue
    }
    if (trimmed.startsWith('- ')) {
      listItems.push(trimmed.slice(2))
      continue
    }
    flushList()
    blocks.push(
      <p key={`p-${i}`} className="mb-3 text-sm leading-relaxed text-uamd-800">
        {renderInline(trimmed)}
      </p>,
    )
  }
  flushList()
  return <div>{blocks}</div>
}

function LegalModal({ pageId, onClose }) {
  const page = LEGAL_PAGES[pageId]
  const dialogRef = useRef(null)

  useEffect(() => {
    if (!page) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    dialogRef.current?.focus()
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [page, onClose])

  if (!page) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-uamd-950/70 p-0 backdrop-blur-sm sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="legal-title"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="flex max-h-[92vh] w-full max-w-2xl flex-col rounded-t-3xl border border-uamd-100 bg-white shadow-2xl animate-fade-in-up sm:rounded-3xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-uamd-100 px-5 py-4 sm:px-7">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-uamd-500">UAMD GPT</p>
            <h2 id="legal-title" className="font-display text-xl font-semibold text-uamd-900 sm:text-2xl">
              {page.title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-uamd-100 bg-uamd-50 p-2 text-uamd-700 transition hover:bg-uamd-100"
            aria-label="Mbyll"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-5 sm:px-7 sm:py-6">
          <LegalBody markdown={page.body} />
        </div>
        <div className="border-t border-uamd-100 px-5 py-3 text-center text-xs text-uamd-700/60 sm:px-7">
          © {new Date().getFullYear()} Danjel Kalari · Universiteti “Aleksandër Moisiu” Durrës
        </div>
      </div>
    </div>
  )
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

      <div className="mt-6 space-y-2">
        <div className="inline-flex items-center gap-2 rounded-full border border-uamd-100 bg-uamd-50 px-3 py-1.5 text-xs font-semibold tracking-wide text-uamd-700">
          <ShieldCheck className="h-3.5 w-3.5" />
          Bazuar në burime publike të uamd.edu.al
        </div>
        <p className="text-xs leading-relaxed text-uamd-700/70">
          Kjo përgjigje është gjeneruar nga AI dhe mund të jetë e pasaktë. Verifikoni te burimet zyrtare.
        </p>
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
  const [legalPage, setLegalPage] = useState(null)
  const textareaRef = useRef(null)
  const answerRef = useRef(null)

  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

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
            <div className="mb-4 flex items-start gap-2.5 rounded-2xl border border-amber-200/80 bg-amber-50 px-3.5 py-3 text-amber-950">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
              <p className="text-xs leading-relaxed sm:text-sm">
                <span className="font-semibold">Njoftim AI:</span> përgjigjet gjenerohen automatikisht
                dhe mund të jenë të pasakta. Verifikoni gjithmonë te{' '}
                <a
                  href="https://uamd.edu.al/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-semibold underline underline-offset-2"
                >
                  uamd.edu.al
                </a>
                .{' '}
                <button
                  type="button"
                  onClick={() => setLegalPage('ai')}
                  className="font-semibold underline underline-offset-2"
                >
                  Lexo njoftimin e plotë
                </button>
              </p>
            </div>

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
              placeholder="Shkruaj pyetjen tënde këtu (pa të dhëna personale)..."
              disabled={loading}
              className="w-full resize-none rounded-2xl border border-uamd-100 bg-uamd-50/60 px-4 py-4 text-base text-uamd-950 outline-none transition placeholder:text-uamd-700/40 focus:border-uamd-500 focus:bg-white focus:ring-4 focus:ring-uamd-500/15 disabled:opacity-70"
            />

            <div className="mt-3 flex items-start gap-2 rounded-xl border border-red-100 bg-red-50/80 px-3 py-2.5 text-red-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
              <p className="text-xs leading-relaxed sm:text-[13px]">
                <span className="font-semibold">Mos vendosni të dhëna personale</span> (nota, amza,
                fjalëkalime, NID, dokumente, etj.).{' '}
                <span className="font-semibold">Disclaimer:</span> përgjigjet e AI mund të jenë të
                pasakta ose të paplota dhe nuk zëvendësojnë informacionin zyrtar.
              </p>
            </div>

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

        <footer className="mt-12 space-y-4 text-center text-xs text-white/35">
          <nav
            aria-label="Informacione ligjore"
            className="flex flex-wrap items-center justify-center gap-x-3 gap-y-2 text-white/55"
          >
            {FOOTER_LINKS.map((link, idx) => (
              <span key={link.id} className="inline-flex items-center gap-3">
                {idx > 0 && <span className="text-white/20" aria-hidden="true">·</span>}
                <button
                  type="button"
                  onClick={() => setLegalPage(link.id)}
                  className="transition hover:text-white hover:underline hover:underline-offset-2"
                >
                  {link.label}
                </button>
              </span>
            ))}
          </nav>

          <div className="space-y-2">
            <p>Ky chatbot është aktualisht në fazë testimi dhe zhvillimi.</p>
            <p>Zhvilluar nga Drejtoria e IT-së, Sektori i Inovacionit dhe Software-it.</p>
            <p>
              © {new Date().getFullYear()} Universiteti “Aleksandër Moisiu” Durrës (UAMD) · UAMD GPT
            </p>
            <p>© {new Date().getFullYear()} Danjel Kalari. Të gjitha të drejtat e rezervuara.</p>
          </div>
        </footer>
      </div>

      {legalPage && <LegalModal pageId={legalPage} onClose={() => setLegalPage(null)} />}
    </div>
  )
}
