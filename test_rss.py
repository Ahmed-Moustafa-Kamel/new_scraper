"""
test_rss.py
-----------
Flow:
  1. Fetch Google News RSS for almasryalyoum
  2. Resolve Google redirect → lands on author page
  3. Find real /news/details/ article links on that author page
  4. Extract text from those real article URLs using Playwright
  5. Print results

Run:
    python test_rss.py
"""

import asyncio
import re
import chardet
import urllib3
from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ── Config ────────────────────────────────────────────────────────────────────

QUERY           = "vodafone"
SITE_DOMAIN     = "almasryalyoum.com"
SITE_NAME       = "almasryalyoum"
MAX_RSS_ENTRIES = 5    # how many RSS entries to process
MAX_ARTICLES    = 3    # how many articles to extract per author page

GOOGLE_RSS = (
    "https://news.google.com/rss/search"
    "?q=site:{domain}+{query}&hl=ar&gl=EG&ceid=EG:ar"
)

# Bypass Google consent page
GOOGLE_CONSENT_COOKIES = [
    {
        "name":   "CONSENT",
        "value":  "YES+cb.20210720-07-p0.en+FX+410",
        "domain": ".google.com",
        "path":   "/",
    },
    {
        "name":   "SOCS",
        "value":  "CAESEwgDEgk0NTM4MzkyMzIaAmVuIAEaBgiAo_CmBg",
        "domain": ".google.com",
        "path":   "/",
    },
]

ARTICLE_PATTERN = re.compile(r"/news/details/\d+")


# ── Step 1: Fetch RSS ─────────────────────────────────────────────────────────

def fetch_rss(query, domain):
    url  = GOOGLE_RSS.format(domain=domain, query=query)
    print(f"RSS URL: {url}\n")
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:MAX_RSS_ENTRIES]:
        articles.append({
            "google_url":   entry.get("link", ""),
            "rss_title":    entry.get("title", ""),
            "published_at": entry.get("published", ""),
        })
    print(f"✅ RSS fetched — {len(articles)} entries found\n")
    return articles


# ── Step 2: Resolve Google URL → author page ──────────────────────────────────

async def resolve_url(context, google_url):
    page = await context.new_page()
    try:
        await context.add_cookies(GOOGLE_CONSENT_COOKIES)
        await page.goto(google_url, wait_until="load", timeout=30000)
        await page.wait_for_timeout(2000)
        return page.url
    finally:
        await page.close()


# ── Step 3: Find /news/details/ links on the author page ─────────────────────

async def find_article_links(context, author_page_url):
    page = await context.new_page()
    try:
        await page.goto(author_page_url, wait_until="load", timeout=30000)
        await page.wait_for_timeout(2000)

        content = await page.content()
        soup    = BeautifulSoup(content, "html.parser")

        found = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ARTICLE_PATTERN.search(href):
                # Make sure it's a full URL
                if href.startswith("/"):
                    href = f"https://www.almasryalyoum.com{href}"
                found.add(href)

        return list(found)[:MAX_ARTICLES]
    finally:
        await page.close()


# ── Step 4: Extract article text using Playwright ─────────────────────────────

NOISE_TAGS = ["script", "style", "noscript", "iframe", "nav", "footer",
              "header", "aside", "form", "button", "figure", "svg"]

NOISE_CLASSES = re.compile(
    r"(comment|share|social|related|sidebar|widget|"
    r"newsletter|popup|banner|ad[-_]|sponsor|pagination)", re.I)

def clean_arabic(text):
    if not text:
        return ""
    text = re.sub(r'<.*?>', ' ', text)
    text = re.sub(r'[ـ]+',  '',  text)
    text = re.sub(r'\s+',   ' ', text).strip()
    return text

def get_meta(soup, *names):
    for name in names:
        tag = (soup.find("meta", property=name)
               or soup.find("meta", attrs={"name": name}))
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return ""

def parse_html(html, url):
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if not hasattr(tag, "attrs") or not tag.attrs:
            continue
        cls = " ".join(tag.get("class", []))
        if NOISE_CLASSES.search(cls) or NOISE_CLASSES.search(tag.get("id", "")):
            tag.decompose()

    text = "\n".join(
        ln.strip() for ln in soup.get_text(separator="\n").splitlines()
        if ln.strip() and len(ln.strip()) > 3
    )

    return {
        "url":          url,
        "title":        clean_arabic(get_meta(soup, "og:title", "twitter:title")),
        "description":  clean_arabic(get_meta(soup, "og:description", "description")),
        "author":       get_meta(soup, "article:author", "author"),
        "published_at": get_meta(soup, "article:published_time", "pubdate", "date"),
        "word_count":   len(text.split()),
        "text_preview": clean_arabic(text)[:400],
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }

async def extract_article(context, url):
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="load", timeout=30000)
        await page.wait_for_timeout(2000)
        html  = await page.content()
        title = await page.title()
        result = parse_html(html, url)
        if not result["title"]:
            result["title"] = clean_arabic(title)
        return result
    except Exception as e:
        return {"url": url, "error": str(e)}
    finally:
        await page.close()


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print(f"Site: {SITE_NAME} | Query: {QUERY}")
    print("=" * 60 + "\n")

    # Step 1 — Fetch RSS
    rss_entries = fetch_rss(QUERY, SITE_DOMAIN)
    if not rss_entries:
        print("❌ No RSS entries found.")
        return

    all_articles = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ar-EG",
        )

        for i, entry in enumerate(rss_entries, 1):
            print(f"{'='*50}")
            print(f"[RSS {i}/{len(rss_entries)}] {entry['rss_title'][:60]}")

            # Step 2 — Resolve Google URL
            try:
                author_url = await resolve_url(context, entry["google_url"])
                print(f"  Author page : {author_url[:80]}")
            except Exception as e:
                print(f"  ❌ Resolve failed: {e}")
                continue

            if "google.com" in author_url:
                print("  ⚠️  Still on Google — skipping")
                continue

            # Step 3 — Find article links on author page
            article_links = await find_article_links(context, author_url)
            print(f"  Found {len(article_links)} article links:")
            for lnk in article_links:
                print(f"    → {lnk}")

            if not article_links:
                print("  ⚠️  No /news/details/ links found on this page")
                continue

            # Step 4 — Extract each article
            for j, article_url in enumerate(article_links, 1):
                print(f"\n  [{j}/{len(article_links)}] Extracting: {article_url}")
                result = await extract_article(context, article_url)

                if "error" in result:
                    print(f"    ❌ Error: {result['error']}")
                else:
                    print(f"    ✅ Title      : {result['title'][:60]}")
                    print(f"    ✅ Words      : {result['word_count']}")
                    print(f"    ✅ Published  : {result['published_at']}")
                    print(f"    ✅ Preview    : {result['text_preview'][:200]}")
                    all_articles.append(result)

            print()

        await browser.close()

    print("=" * 60)
    print(f"✅ Total articles extracted: {len(all_articles)}")
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())