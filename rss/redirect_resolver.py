import asyncio
import re
import chardet
import urllib3
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from readability import Document
from bs4 import BeautifulSoup

from playwright.async_api import async_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# HTTP Session Config for Content Extraction
# ==========================================

def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://",  adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ar,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return session

SESSION = _make_session()

# ==========================================
# Text Cleaning & Normalization Helpers
# ==========================================

def clean_arabic(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<.*?>',  ' ', text)
    text = re.sub(r'[ـ]+',   '', text)
    return re.sub(r'\s+',    ' ', text).strip()

NOISE_TAGS = ["script", "style", "noscript", "iframe", "nav", "footer", "header",
              "aside", "form", "button", "figure", "figcaption", "svg", "ads", "advertisement"]
NOISE_CLASSES = re.compile(
    r"(comment|share|social|related|sidebar|widget|breadcrumb|"
    r"newsletter|popup|banner|ad[-_]|sponsor|tag|pagination)", re.I)

def _remove_noise(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag is None or not hasattr(tag, "attrs") or tag.attrs is None:
            continue
        cls = " ".join(tag.get("class", []))
        if NOISE_CLASSES.search(cls) or NOISE_CLASSES.search(tag.get("id", "")):
            tag.decompose()
    return soup

def _clean_text(raw: str) -> str:
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln and len(ln) > 3]
    return "\n".join(lines)

def _get_meta(soup: BeautifulSoup, *names) -> str:
    for name in names:
        tag = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return ""

# ==========================================
# Core HTML Content Parser Engine
# ==========================================

def _extract_from_url(url: str) -> dict:
    """Fetch and parse article body text using requests + readability."""
    try:
        response = SESSION.get(url, timeout=12, verify=False)
        response.raise_for_status()
    except Exception as exc:
        raise ValueError(f"Failed to fetch: {exc}")

    declared = response.encoding or ""
    if not declared or declared.lower() in ("iso-8859-1", "latin-1"):
        detected = chardet.detect(response.content)
        encoding = detected.get("encoding") or "utf-8"
    else:
        encoding = declared
    html = response.content.decode(encoding, errors="replace")

    doc          = Document(html)
    clean_html   = doc.summary()
    full_soup    = BeautifulSoup(html,       "html.parser")
    article_soup = BeautifulSoup(clean_html, "html.parser")

    _remove_noise(article_soup)
    text = _clean_text(article_soup.get_text(separator="\n"))

    if len(text) < 200:
        _remove_noise(full_soup)
        for tag in full_soup(["p", "h1", "h2", "h3", "h4", "blockquote"]):
            tag.insert_after("\n")
        text = _clean_text(full_soup.get_text(separator="\n"))

    title       = _get_meta(full_soup, "og:title", "twitter:title") or (full_soup.title.string.strip() if full_soup.title else "")
    description = _get_meta(full_soup, "og:description", "description", "twitter:description")
    author      = _get_meta(full_soup, "article:author", "author", "byl")
    site_name   = _get_meta(full_soup, "og:site_name")
    language    = full_soup.html.get("lang", "") if full_soup.html else ""

    return {
        "title":        clean_arabic(title),
        "description":  clean_arabic(description),
        "author":       author,
        "site_name":    site_name,
        "language":     language,
        "word_count":   len(text.split()),
        "text":         clean_arabic(text),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "error":        "",
    }

# ==========================================
# Google News URL Resolver
# ==========================================

# Bypass Google consent page
GOOGLE_CONSENT_COOKIES = [
    {"name": "CONSENT", "value": "YES+cb.20210720-07-p0.en+FX+410",
     "domain": ".google.com", "path": "/"},
    {"name": "SOCS",    "value": "CAESEwgDEgk0NTM4MzkyMzIaAmVuIAEaBgiAo_CmBg",
     "domain": ".google.com", "path": "/"},
]


async def _resolve_google_url(context, google_url: str) -> str:
    """
    Resolve a Google News redirect URL to the real article URL.

    How Google News redirects work:
      1. Browser opens news.google.com/rss/articles/CBMi...
      2. Google runs JS that redirects to the real article URL
      3. This requires a real browser with JS enabled — no curl/requests trick works

    Strategy:
      1. Inject consent cookies (skip consent page)
      2. Navigate to the Google URL and wait for JS redirect
      3. Poll every 300ms for up to 15 seconds until URL changes
      4. If still on Google, scan page for non-Google links
    """
    if "news.google.com" not in google_url:
        return google_url  # not a Google URL, return as-is

    page = await context.new_page()
    try:
        # Inject consent cookies before any navigation
        await context.add_cookies(GOOGLE_CONSENT_COOKIES)

        # Navigate — Google JS will trigger a redirect
        try:
            await page.goto(google_url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass  # timeout is ok — redirect may have already happened

        # Poll for redirect to complete (up to 15 seconds)
        for _ in range(50):  # 50 × 300ms = 15s
            current = page.url
            if "news.google.com" not in current and "google.com" not in current:
                return current  # ✅ redirected to real article
            await page.wait_for_timeout(300)

        # Still on Google — try to find real article link in page HTML
        try:
            content = await page.content()
            soup    = BeautifulSoup(content, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("http") and "google.com" not in href:
                    return href
        except Exception:
            pass

        # Could not resolve — return original so caller can handle
        return google_url

    except Exception as e:
        return google_url
    finally:
        await page.close()


async def _process_row(context, row: dict) -> dict:
    """Resolve URL then extract article text."""

    # Step 1 — resolve real URL
    try:
        real_url = await _resolve_google_url(context, row["url"])
    except Exception as exc:
        return {
            "url":          row["url"],
            "word_count":   None,
            "text":         "",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "error":        f"Redirect failed: {exc}",
        }

    # Still on Google — could not resolve
    if "google.com" in real_url:
        return {
            "url":          row["url"],
            "word_count":   None,
            "text":         "",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "error":        "Could not resolve Google redirect — skipped",
        }

    # Step 2 — extract article text using requests (fast, no browser needed)
    try:
        loop      = asyncio.get_event_loop()
        extracted = await loop.run_in_executor(None, _extract_from_url, real_url)
        return {"url": real_url, **extracted}
    except Exception as exc:
        return {
            "url":          real_url,
            "word_count":   None,
            "text":         "",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "error":        f"Extraction failed: {exc}",
        }


async def resolve_and_extract_async(df, max_concurrent: int = 5):
    if df.empty:
        return df

    rows    = df.to_dict("records")
    results = [None] * len(rows)
    total   = len(rows)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]
        )
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )

        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        semaphore = asyncio.Semaphore(max_concurrent)

        async def worker(i, row):
            async with semaphore:
                try:
                    result = await _process_row(context, row)
                    status = "✅" if not result.get("error") else "❌"
                    words  = result.get("word_count") or 0
                    url_display = result["url"][:70]
                    print(f"  {status} [{i+1}/{total}] {words:>5} words → {url_display}")
                    if result.get("error"):
                        print(f"       ⚠️  {result['error']}")
                    results[i] = result
                except Exception as exc:
                    results[i] = {
                        "url":          row["url"],
                        "word_count":   None,
                        "text":         "",
                        "extracted_at": datetime.now(timezone.utc).isoformat(),
                        "error":        f"Worker failed: {exc}",
                    }

        await asyncio.gather(*[worker(i, row) for i, row in enumerate(rows)])
        await context.close()
        await browser.close()

    for i, update in enumerate(results):
        if update:
            for col, val in update.items():
                df.at[i, col] = val

    return df


def resolve_and_extract(df, max_concurrent: int = 5):
    """Sync entry point."""
    return asyncio.run(resolve_and_extract_async(df, max_concurrent=max_concurrent))