import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from readability import Document
from bs4 import BeautifulSoup
import chardet
import re
import pandas as pd
from datetime import datetime, timedelta
from dateutil import parser as dateparser
from concurrent.futures import ThreadPoolExecutor, as_completed

from scraper import scrape_links

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ── Session with automatic retries ────────────────────────────────────────────
def make_session() -> requests.Session:
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
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return session


SESSION = make_session()


# ── Date normalizer ───────────────────────────────────────────────────────────
def parse_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        return dateparser.parse(raw).strftime("%Y-%m-%d")
    except Exception:
        return ""


# ── Metadata helpers ──────────────────────────────────────────────────────────
def get_meta(soup: BeautifulSoup, *names) -> str:
    for name in names:
        tag = (
            soup.find("meta", property=name)
            or soup.find("meta", attrs={"name": name})
        )
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return ""


def extract_metadata(soup: BeautifulSoup, url: str) -> dict:
    return {
        "url":          url,
        "title":        get_meta(soup, "og:title", "twitter:title") or (soup.title.string.strip() if soup.title else ""),
        "description":  get_meta(soup, "og:description", "description", "twitter:description"),
        "author":       get_meta(soup, "article:author", "author", "byl"),
        "published_at": parse_date(get_meta(soup, "article:published_time", "pubdate", "date")),
        "site_name":    get_meta(soup, "og:site_name"),
        "language":     soup.html.get("lang", "") if soup.html else "",
    }


# ── Noise removal ─────────────────────────────────────────────────────────────
NOISE_TAGS = [
    "script", "style", "noscript", "iframe", "nav", "footer",
    "header", "aside", "form", "button", "figure", "figcaption",
    "svg", "ads", "advertisement",
]

NOISE_CLASSES = re.compile(
    r"(comment|share|social|related|sidebar|widget|breadcrumb|"
    r"newsletter|popup|banner|ad[-_]|sponsor|tag|pagination)",
    re.I,
)

def remove_noise(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag is None or not hasattr(tag, "attrs") or tag.attrs is None:
            continue
        cls = " ".join(tag.get("class", []))
        if NOISE_CLASSES.search(cls) or NOISE_CLASSES.search(tag.get("id", "")):
            tag.decompose()
    return soup


# ── Text cleaning ─────────────────────────────────────────────────────────────
def clean_text(raw: str) -> str:
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]
    lines = [ln for ln in lines if len(ln) > 3]
    return "\n".join(lines)


def clean_arabic(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<.*?>',  ' ', text)
    text = re.sub(r'[ـ]+',   '',  text)
    text = re.sub(r'\s+',    ' ', text).strip()
    return text


# ── Main extractor ────────────────────────────────────────────────────────────
def extract_clean_text(url: str) -> dict:
    try:
        response = SESSION.get(url, timeout=15, verify=False)
        response.raise_for_status()
    except requests.RequestException as e:
        return {"error": str(e), "url": url}

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

    remove_noise(article_soup)
    raw_text = article_soup.get_text(separator="\n")
    text     = clean_text(raw_text)

    if len(text) < 200:
        remove_noise(full_soup)
        for tag in full_soup(["p", "h1", "h2", "h3", "h4", "blockquote"]):
            tag.insert_after("\n")
        raw_text = full_soup.get_text(separator="\n")
        text     = clean_text(raw_text)

    metadata   = extract_metadata(full_soup, url)
    word_count = len(text.split())

    return {
        "metadata":     metadata,
        "text":         text,
        "word_count":   word_count,
        "extracted_at": datetime.utcnow().isoformat(),
    }


# ── Worker ────────────────────────────────────────────────────────────────────
def process_row(args):
    idx, total, site, tier, url = args
    print(f"[{idx}/{total}] {site} ({tier}) — {url[:70]}")

    result = extract_clean_text(url)

    if "error" in result:
        print(f"  [ERROR] {result['error']}")
        return {
            "site": site, "tier": tier, "url": url,
            "title": "", "author": "", "published_at": "",
            "description": "", "site_name": "", "language": "",
            "word_count": 0, "text": "",
            "extracted_at": datetime.utcnow().isoformat(),
            "error": result["error"],
        }

    m = result["metadata"]
    print(f"  OK — {result['word_count']} words — {m['title'][:50]}")

    return {
        "site":         site,
        "tier":         tier,
        "url":          m["url"],
        "title":        clean_arabic(m["title"]),
        "author":       m["author"],
        "published_at": m["published_at"],
        "description":  clean_arabic(m["description"]),
        "site_name":    m["site_name"],
        "language":     m["language"],
        "word_count":   result["word_count"],
        "text":         clean_arabic(result["text"]),
        "extracted_at": result["extracted_at"],
        "error":        "",
    }


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":

    SCRAPER_WORKERS   = int(os.environ.get("SCRAPER_WORKERS",   "2"))
    EXTRACTOR_WORKERS = int(os.environ.get("EXTRACTOR_WORKERS", "10"))
    FILTER_DAYS       = int(os.environ.get("FILTER_DAYS",       "30"))

    queries = [
        "orange", "اورنج", "فودافون", "vodafone", "اتصالات", "etisalat",
        "اتصالات / اي اند", "المصرية للاتصالات", "we", "telecom egypt",
        "قطاع الاتصالات", "الحكومة المصرية", "وزير الاستثمار المصري",
        "البنك المركزي", "central bank", "وزير المالية", "رئيس الوزراء",
        "ريادة الأعمال", "entrepreneurship", "الابتكار و التكنولوجيا",
        "تنظيم الاتصالات", "ntra", "البنك الدولي", "world bank",
        "البورصة المصرية", "egx",
    ]

    # ── Step 1: Scrape links ──────────────────────────────────────────────────
    scraped_df = scrape_links(queries, max_workers=SCRAPER_WORKERS)
    total      = len(scraped_df)
    print(f"\nExtracting {total} articles with {EXTRACTOR_WORKERS} threads...\n")

    if total == 0:
        print("⚠️  No links found — exiting.")
        exit(0)

    # ── Step 2: Extract article text ─────────────────────────────────────────
    tasks = [
        (i + 1, total, row["site"], row["tier"], row["link"])
        for i, (_, row) in enumerate(scraped_df.iterrows())
    ]

    rows = []
    with ThreadPoolExecutor(max_workers=EXTRACTOR_WORKERS) as executor:
        futures = {executor.submit(process_row, task): task for task in tasks}
        for future in as_completed(futures):
            rows.append(future.result())

    df = pd.DataFrame(rows)

    # ── Step 3: Filter by date (optional) ────────────────────────────────────
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
    before = len(df)
    # Uncomment to enable date filtering:
    # df = df[df["published_at"] >= datetime.utcnow() - timedelta(days=FILTER_DAYS)]
    df["published_at"] = df["published_at"].dt.strftime("%Y-%m-%d")
    print(f"  Kept {len(df)} articles (filtered {before - len(df)} old)")

    # ── Step 4: Save CSV ──────────────────────────────────────────────────────
    output_file = os.environ.get("OUTPUT_FILE", "articles.csv")
    df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\n✅ Saved {len(df)} rows to {output_file}")