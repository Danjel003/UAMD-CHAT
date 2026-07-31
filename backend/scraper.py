"""
UAMD GPT — Domain-restricted scraper for uamd.edu.al
Fetches HTML pages (BeautifulSoup) and PDF documents (PyMuPDF).
Optimized: parallel downloads + in-memory page cache.
"""

from __future__ import annotations

import hashlib
import io
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup

ALLOWED_HOSTS = {"uamd.edu.al", "www.uamd.edu.al"}
# Official portals linked from uamd.edu.al (admissions system)
ALLOWED_EXTRA_HOSTS = {"admissions.prime-solutions.al"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 12
MAX_HTML_CHARS = 22_000
MAX_PDF_CHARS = 24_000
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
PAGE_CACHE_TTL = 1800  # 30 minutes
MAX_WORKERS = 5

_page_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def is_uamd_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return host in ALLOWED_HOSTS or host.endswith(".uamd.edu.al")
    except Exception:
        return False


# Also allow direct file URLs on the university domain (xlsx/pdf uploads)
def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host in ALLOWED_HOSTS or host.endswith(".uamd.edu.al"):
            return True
        if host in ALLOWED_EXTRA_HOSTS:
            return True
        return False
    except Exception:
        return False


def is_pdf_url(url: str, content_type: str | None = None) -> bool:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return True
    if content_type and "application/pdf" in content_type.lower():
        return True
    return False


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "sq,en;q=0.8",
        }
    )
    return s


def clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_html_text(html: str, base_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True) or title

    footer_text = ""
    footer = soup.find("footer")
    if footer:
        footer_text = clean_text(footer.get_text("\n", strip=True))

    contacts: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip()
            if email and email != "#":
                contacts.append(f"Email: {email}")
        elif href.startswith("tel:"):
            contacts.append(f"Tel: {href.replace('tel:', '')}")

    # UAMD uses Kingster / GoodLayers page builder — prefer those containers
    candidates: list[str] = []
    for sel in [
        "main",
        "article",
        "[role='main']",
        "#kingster-page-wrapper",
        ".gdlr-core-page-builder-body",
        ".gdlr-core-pbf-wrapper",
        ".entry-content",
        ".post-content",
        ".elementor-widget-theme-post-content",
    ]:
        for el in soup.select(sel):
            txt = clean_text(el.get_text("\n", strip=True))
            if len(txt) >= 80:
                candidates.append(txt)

    if not candidates:
        body = soup.find("body") or soup
        candidates.append(clean_text(body.get_text("\n", strip=True)))

    # Longest block wins (avoids empty theme "content" shells)
    text = max(candidates, key=len)
    if footer_text and footer_text in text:
        text = text.replace(footer_text, "").strip()

    extras: list[str] = []
    if contacts:
        extras.append("Kontaktet e gjetura në faqe:\n" + "\n".join(dict.fromkeys(contacts)))
    if footer_text and len(footer_text) > 40:
        short_footer = footer_text.split("Menu")[0].strip()
        if len(short_footer) > 40:
            extras.append("Informacion nga footer:\n" + short_footer[:1200])
    if extras:
        text = (text + "\n\n" + "\n\n".join(extras)).strip()
    if len(text) > MAX_HTML_CHARS:
        text = text[:MAX_HTML_CHARS]

    pdf_links: list[str] = []
    file_links: list[str] = []
    child_links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = normalize_url(urljoin(base_url, a["href"]))
        low = href.lower()
        host_ok = is_uamd_url(href) or "uamd.edu.al" in urlparse(href).netloc
        if not host_ok:
            continue
        if low.endswith(".pdf"):
            pdf_links.append(href)
            file_links.append(href)
        elif low.endswith((".xlsx", ".xls")):
            file_links.append(href)
        path = urlparse(href).path.lower()
        if any(k in path for k in ("departament", "bachelor", "master", "program")):
            child_links.append(href)

    return {
        "title": title,
        "text": text,
        "pdf_links": list(dict.fromkeys(pdf_links))[:8],
        "file_links": list(dict.fromkeys(file_links))[:8],
        "child_links": list(dict.fromkeys(child_links))[:8],
    }


def extract_pdf_text(content: bytes) -> str:
    doc = fitz.open(stream=io.BytesIO(content), filetype="pdf")
    parts: list[str] = []
    try:
        for page in list(doc)[:20]:
            parts.append(page.get_text("text"))
    finally:
        doc.close()
    text = clean_text("\n\n".join(parts))
    if len(text) > MAX_PDF_CHARS:
        text = text[:MAX_PDF_CHARS]
    return text


def extract_xlsx_text(content: bytes) -> str:
    """Extract readable strings from xlsx without openpyxl."""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = set(zf.namelist())
            texts: list[str] = []
            if "xl/sharedStrings.xml" in names:
                xml = zf.read("xl/sharedStrings.xml").decode("utf-8", errors="ignore")
                texts = re.findall(r"<t[^>]*>(.*?)</t>", xml)
            # Fallback: scan worksheets for inline strings
            if not texts:
                for name in names:
                    if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                        xml = zf.read(name).decode("utf-8", errors="ignore")
                        texts.extend(re.findall(r"<t[^>]*>(.*?)</t>", xml))
            cleaned = []
            for t in texts:
                t = re.sub(r"\s+", " ", t).strip()
                if t:
                    cleaned.append(t)
            return clean_text("\n".join(dict.fromkeys(cleaned)))
    except Exception:
        return ""


def _cache_get(url: str) -> dict[str, Any] | None:
    with _cache_lock:
        item = _page_cache.get(url)
        if not item:
            return None
        ts, doc = item
        if time.time() - ts > PAGE_CACHE_TTL:
            _page_cache.pop(url, None)
            return None
        return dict(doc)


def _cache_set(url: str, doc: dict[str, Any]) -> None:
    with _cache_lock:
        _page_cache[url] = (time.time(), dict(doc))


def fetch_url(url: str, use_cache: bool = True) -> dict[str, Any]:
    """Download and extract content from an allowed official URL."""
    url = normalize_url(url)
    if not is_allowed_url(url):
        return {
            "url": url,
            "title": "",
            "text": "",
            "content_type": "",
            "ok": False,
            "error": "domain_not_allowed",
        }

    if use_cache:
        cached = _cache_get(url)
        if cached is not None:
            cached["cached"] = True
            return cached

    try:
        with _session() as session:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
            final_url = normalize_url(resp.url)
            if not is_allowed_url(final_url):
                return {
                    "url": url,
                    "title": "",
                    "text": "",
                    "content_type": "",
                    "ok": False,
                    "error": "redirect_outside_domain",
                }

            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    return {
                        "url": final_url,
                        "title": "",
                        "text": "",
                        "content_type": content_type,
                        "ok": False,
                        "error": "file_too_large",
                    }
                chunks.append(chunk)
            raw = b"".join(chunks)

            if resp.status_code >= 400:
                return {
                    "url": final_url,
                    "title": "",
                    "text": "",
                    "content_type": content_type,
                    "ok": False,
                    "error": f"http_{resp.status_code}",
                }

            if is_pdf_url(final_url, content_type):
                text = extract_pdf_text(raw)
                title = urlparse(final_url).path.split("/")[-1] or "dokument.pdf"
                doc = {
                    "url": final_url,
                    "title": title,
                    "text": text,
                    "content_type": "application/pdf",
                    "pdf_links": [],
                    "file_links": [],
                    "child_links": [],
                    "ok": bool(text.strip()),
                    "error": None if text.strip() else "empty_pdf",
                }
            elif final_url.lower().endswith((".xlsx", ".xls")) or "spreadsheet" in content_type:
                text = extract_xlsx_text(raw)
                title = urlparse(final_url).path.split("/")[-1] or "tabele.xlsx"
                doc = {
                    "url": final_url,
                    "title": title,
                    "text": f"Të dhëna nga dokumenti tabular {title}:\n{text}",
                    "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "pdf_links": [],
                    "file_links": [],
                    "child_links": [],
                    "ok": bool(text.strip()),
                    "error": None if text.strip() else "empty_xlsx",
                }
            else:
                html = raw.decode(resp.encoding or "utf-8", errors="replace")
                extracted = extract_html_text(html, final_url)
                doc = {
                    "url": final_url,
                    "title": extracted["title"],
                    "text": extracted["text"],
                    "content_type": "text/html",
                    "pdf_links": extracted.get("pdf_links") or [],
                    "file_links": extracted.get("file_links") or [],
                    "child_links": extracted.get("child_links") or [],
                    "ok": bool(extracted["text"].strip()),
                    "error": None if extracted["text"].strip() else "empty_html",
                }

            if doc.get("ok"):
                _cache_set(final_url, doc)
                if final_url != url:
                    _cache_set(url, doc)
            return doc
    except Exception as exc:
        return {
            "url": url,
            "title": "",
            "text": "",
            "content_type": "",
            "ok": False,
            "error": str(exc),
        }


def fetch_many(
    urls: list[str],
    max_docs: int = 5,
    include_pdfs: bool = False,
) -> list[dict[str, Any]]:
    """Fetch unique official URLs in parallel, then enrich with department/program files."""
    pending: list[str] = []
    seen: set[str] = set()
    for u in urls:
        nu = normalize_url(u)
        if is_allowed_url(nu) and nu not in seen:
            seen.add(nu)
            pending.append(nu)
        if len(pending) >= max_docs:
            break

    results: list[dict[str, Any]] = []
    if not pending:
        return results

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(pending))) as pool:
        futures = {pool.submit(fetch_url, url): url for url in pending}
        for fut in as_completed(futures):
            doc = fut.result()
            if doc.get("ok") and doc.get("text"):
                results.append(doc)

    # Enrich with department pages + tabular/PDF attachments discovered on faculty pages
    extra: list[str] = []
    for doc in list(results):
        for link in (doc.get("child_links") or []) + (doc.get("file_links") or []):
            if link not in seen and is_allowed_url(link):
                seen.add(link)
                extra.append(link)
        if include_pdfs:
            for pdf in doc.get("pdf_links") or []:
                if pdf not in seen and is_allowed_url(pdf):
                    seen.add(pdf)
                    extra.append(pdf)
        if len(results) + len(extra) >= max_docs + 3:
            break

    # Always try known FTI department/xlsx if faculty page was requested
    for u in pending:
        if "teknologjise-se-informacionit" in u or "/fti" in u:
            for bonus in [
                "https://uamd.edu.al/departamenti-i-teknologjise-se-informacionit/",
                "https://uamd.edu.al/wp-content/uploads/2024/04/FTI.xlsx",
            ]:
                if bonus not in seen:
                    seen.add(bonus)
                    extra.append(bonus)

    extra = extra[: max(0, (max_docs + 3) - len(results))]
    if extra:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(extra))) as pool:
            for fut in as_completed({pool.submit(fetch_url, u): u for u in extra}):
                doc = fut.result()
                if doc.get("ok") and doc.get("text"):
                    results.append(doc)

    order = {u: i for i, u in enumerate(pending + extra)}
    results.sort(key=lambda d: order.get(normalize_url(d["url"]), 999))
    return results[: max(max_docs, min(len(results), max_docs + 2))]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
