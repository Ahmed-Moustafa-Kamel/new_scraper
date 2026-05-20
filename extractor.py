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
from datetime import datetime
from dateutil import parser as dateparser
from concurrent.futures import ThreadPoolExecutor, as_completed

from scraper import scrape_links

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ar,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return session

SESSION = make_session()

def parse_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        return dateparser.parse(raw).strftime("%Y-%m-%d")
    except Exception:
        return ""

def get_meta(soup: BeautifulSoup, *names) -> str:
    for name in names:
        tag = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return ""

def extract_metadata(soup: BeautifulSoup, url: str) -> dict:
    return {
        "url": url,
        "title": get_meta(soup, "og:title", "twitter:title") or (soup.title.string.strip() if soup.title else ""),
        "description": get_meta(soup, "og:description", "description", "twitter:description"),
        "author": get_meta(soup, "article:author", "author", "byl"),
        "published_at": parse_date(get_meta(soup, "article:published_time", "pubdate", "date")),
        "site_name": get_meta(soup, "og:site_name"),
        "language": soup.html.get("lang", "") if soup.html else "",
    }

NOISE_TAGS = ["script", "style", "noscript", "iframe", "nav", "footer", "header", "aside", "form", "button", "figure", "figcaption", "svg", "ads", "advertisement"]
NOISE_CLASSES = re.compile(r"(comment|share|social|related|sidebar|widget|breadcrumb|newsletter|popup|banner|ad[-_]|sponsor|tag|pagination)", re.I)

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

def clean_text(raw: str) -> str:
    lines = [ln.strip() for ln in raw.splitlines()]
    return "\n".join([ln for ln in lines if ln and len(ln) > 3])

def clean_arabic(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<.*?>', ' ', text)
    text = re.sub(r'[ـ]+', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def extract_clean_text(url: str) -> dict:
    try:
        response = SESSION.get(url, timeout=15, verify=False)
        response.raise_for_status()
    except Exception as e:
        return {"error": str(e), "url": url}

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

    remove_noise(article_soup)
    text = clean_text(article_soup.get_text(separator="\n"))

    if len(text) < 200:
        remove_noise(full_soup)
        for tag in full_soup(["p", "h1", "h2", "h3", "h4", "blockquote"]):
            tag.insert_after("\n")
        text = clean_text(full_soup.get_text(separator="\n"))

    metadata = extract_metadata(full_soup, url)
    return {
        "metadata": metadata,
        "text": text,
        "word_count": len(text.split()),
        "extracted_at": datetime.utcnow().isoformat(),
    }

def process_row(args):
    idx, total, site, tier, url = args
    result = extract_clean_text(url)

    if "error" in result:
        return {
            "site": site, "tier": tier, "url": url, "title": "", "author": "",
            "published_at": "", "description": "", "site_name": "", "language": "",
            "word_count": 0, "text": "", "extracted_at": datetime.utcnow().isoformat(), "error": result["error"]
        }

    m = result["metadata"]
    return {
        "site": site, "tier": tier, "url": m["url"], "title": clean_arabic(m["title"]),
        "author": m["author"], "published_at": m["published_at"], "description": clean_arabic(m["description"]),
        "site_name": m["site_name"], "language": m["language"], "word_count": result["word_count"],
        "text": clean_arabic(result["text"]), "extracted_at": result["extracted_at"], "error": ""
    }

if __name__ == "__main__":
    EXTRACTOR_WORKERS = int(os.environ.get("EXTRACTOR_WORKERS", "10"))
    
    queries = [
        "orange", "اورنج", "فودافون", "vodafone", "اتصالات", "etisalat",
        "المصرية للاتصالات", "we", "البنك المركزي", "تنظيم الاتصالات", "ntra"
    ]

    scraped_df = scrape_links(queries)
    total = len(scraped_df)
    
    if total == 0:
        print("⚠️ No links found. Exiting.")
        exit(0)

    tasks = [(i + 1, total, row["site"], row["tier"], row["link"]) for i, (_, row) in enumerate(scraped_df.iterrows())]
    rows = []
    
    with ThreadPoolExecutor(max_workers=EXTRACTOR_WORKERS) as executor:
        futures = {executor.submit(process_row, task): task for task in tasks}
        for future in as_completed(futures):
            rows.append(future.result())

    df = pd.DataFrame(rows)
    output_file = os.environ.get("OUTPUT_FILE", "articles.csv")
    df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\n✅ Saved {len(df)} rows to {output_file}")