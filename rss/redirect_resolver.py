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
from playwright_stealth import stealth_async

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===============================
# HTTP Session 
# ===============================

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

# ===============================
# Helpers
# ===============================

def clean_arabic(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<.*?>',  ' ', text)
    text = re.sub(r'[ـ]+',   '', text)
    return re.sub(r'\s+',    ' ', text).strip()

NOISE_TAGS = ["script", "style", "noscript", "iframe", "nav", "footer", "header", "aside", "form", "button", "figure", "figcaption", "svg", "ads", "advertisement"]
NOISE_CLASSES = re.compile(r"(comment|share|social|related|sidebar|widget|breadcrumb|newsletter|popup|banner|ad[-_]|sponsor|tag|pagination)", re.I)

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

# ===============================
# Core extractor 
# ===============================

def _extract_from_url(url: str) -> dict:
    """Fetch and extract article text using requests + readability + BS4."""
    try:
        response = SESSION.get(url, timeout=12, verify=False)
        response.raise_for_status()
    except Exception as exc:
        raise ValueError(f"Network processing block dropped: {exc}")

    declared = response.encoding or ""
    if not declared or declared.lower() in ("iso-8859-1", "latin-1"):
        detected = chardet.detect(response.content)
        encoding = detected.get("encoding") or "utf-8"
    else:
        encoding = declared
    html = response.content.decode(encoding, errors="replace")

    doc = Document(html)
    clean_html = doc.summary()
    full_soup = BeautifulSoup(html, "html.parser")
    article_soup = BeautifulSoup(clean_html, "html.parser")

    _remove_noise(article_soup)
    text = _clean_text(article_soup.get_text(separator="\n"))

    if len(text) < 200:
        _remove_noise(full_soup)
        for tag in full_soup(["p", "h1", "h2", "h3", "h4", "blockquote"]):
            tag.insert_after("\n")
        text = _clean_text(full_soup.get_text(separator="\n"))

    title = _get_meta(full_soup, "og:title", "twitter:title") or (full_soup.title.string.strip() if full_soup.title else "")
    description = _get_meta(full_soup, "og:description", "description", "twitter:description")
    author = _get_meta(full_soup, "article:author", "author", "byl")
    site_name = _get_meta(full_soup, "og:site_name")
    language = full_soup.html.get("lang", "") if full_soup.html else ""

    return {
        "title": clean_arabic(title),
        "description": clean_arabic(description),
        "author": author,
        "site_name": site_name,
        "language": language,
        "word_count": len(text.split()),
        "text": clean_arabic(text),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "error": "",
    }

# ===============================
# Async pipeline
# ===============================

async def _resolve_url(page, google_url: str) -> str:
    """Navigate the Google redirect and cleanly return the real article URL."""
    # Instantly trigger as soon as structural elements land
    await page.goto(google_url, wait_until="domcontentloaded", timeout=15000)
    # Grab the true target URL string immediately without hanging on missing elements
    return page.url


async def _process_row(page, row: dict) -> dict:
    real_url = row["url"]
    try:
        real_url = await _resolve_url(page, row["url"])
    except Exception as exc:
        return {
            "url": row["url"], "word_count": None, "text": "",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "error": f"Redirect navigation phase timeout: {exc}",
        }

    # If it is an identity link, extract immediately
    try:
        loop = asyncio.get_event_loop()
        extracted = await loop.run_in_executor(None, _extract_from_url, real_url)
        return {"url": real_url, **extracted}
    except Exception as exc:
        return {
            "url": real_url, "word_count": None, "text": "",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "error": f"Text engine processing extraction failed: {exc}",
        }


async def resolve_and_extract_async(df, max_concurrent: int = 5):
    if df.empty:
        return df
        
    rows = df.to_dict("records")
    results = [None] * len(rows)
    total = len(rows)

    BLOCKED_ASSETS = ["image", "media", "font", "stylesheet"]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        semaphore = asyncio.Semaphore(max_concurrent)

        async def worker(i, row):
            async with semaphore:
                page = await context.new_page()
                # Apply stealth configurations safely to our active async context
                await stealth_async(page)
                
                # Block structural visual noise
                await page.route("**/*", lambda route: route.abort() if route.request.resource_type in BLOCKED_ASSETS else route.continue_())
                
                try:
                    result = await _process_row(page, row)
                    status = "✅" if not result["error"] else "❌"
                    words = result.get("word_count") or 0
                    print(f"  {status} [{i+1}/{total}] {words:>5} words extracted → {result['url'][:60]}")
                    results[i] = result
                finally:
                    await page.close()

        await asyncio.gather(*[worker(i, row) for i, row in enumerate(rows)])
        await context.close()
        browser.close()

    # Safely align results back into the source dataframe structure
    for i, update in enumerate(results):
        if update:
            for col, val in update.items():
                df.at[i, col] = val

    return df


def resolve_and_extract(df, max_concurrent: int = 5):
    """Sync runtime entrypoint safe from nested loop exceptions."""
    return asyncio.run(resolve_and_extract_async(df, max_concurrent=max_concurrent))