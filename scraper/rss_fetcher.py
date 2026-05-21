#rss_fetcher
import feedparser
import pandas as pd
from urllib.parse import quote_plus
import re

# ===============================
# Configuration
# ===============================

SITES = {
    "youm7":       ("youm7.com",           "tier1"),
    "almasry":     ("almasryalyoum.com",   "tier1"),
    "akhbarelyom": ("akhbarelyom.com",     "tier2"),
    "alahram":     ("gate.ahram.org.eg",   "tier1"),
}

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=ar&gl=EG&ceid=EG:ar"


# ===============================
# Helpers
# ===============================

def clean_arabic(text):
    """Basic cleaning for Arabic text."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)   # strip HTML tags
    text = text.strip()
    return text


def _parse_entry(entry, site, tier):
    """Map a feedparser entry to the target schema (no real_url / text yet)."""
    return {
        "site":         site,
        "tier":         tier,
        "url":          entry.get("link", ""),          # Google redirect URL (resolved later)
        "title":        clean_arabic(entry.get("title", "")),
        "author":       entry.get("author", ""),
        "published_at": entry.get("published", ""),
        "description":  clean_arabic(entry.get("summary", "")),
        "site_name":    entry.get("source", {}).get("title", site) if hasattr(entry.get("source", None), "get") else site,
        "language":     "ar",
        "word_count":   None,           # filled after extraction
        "text":         "",             # filled after extraction
        "extracted_at": None,           # filled after extraction
        "error":        "",
    }


# ===============================
# Core RSS Functions
# ===============================

def fetch_google_news(query):
    """Fetch general Google News RSS results."""
    encoded_query = quote_plus(query)
    rss_url = GOOGLE_NEWS_RSS.format(query=encoded_query)
    feed = feedparser.parse(rss_url)
    return [_parse_entry(e, site="google_news", tier="general") for e in feed.entries]


def fetch_site_specific(query, site_name, site_domain, tier):
    """Fetch Google News RSS filtered by a specific site."""
    full_query = f"site:{site_domain} {query}"
    encoded_query = quote_plus(full_query)
    rss_url = GOOGLE_NEWS_RSS.format(query=encoded_query)
    feed = feedparser.parse(rss_url)
    return [_parse_entry(e, site=site_name, tier=tier) for e in feed.entries]


def _fetch_single_query(query: str) -> list:
    """Fetch general + site-specific results for one query."""
    results = []
    results.extend(fetch_google_news(query))
    for site_name, (domain, tier) in SITES.items():
        results.extend(fetch_site_specific(query, site_name, domain, tier))
    return results


def fetch_all(queries, since_hours: int = 72) -> pd.DataFrame:
    """
    Fetch:
      1) General Google News results
      2) Site-specific filtered results for every SITE
    """
    if isinstance(queries, str):
        queries = [queries]

    all_results = []
    for i, query in enumerate(queries, 1):
        print(f" 📊 [{i}/{len(queries)}] Extracting RSS matrix for target: {query}")
        all_results.extend(_fetch_single_query(query))

    if not all_results:
        return pd.DataFrame(columns=["site", "tier", "url", "title", "author", "published_at", "description", "site_name", "language", "word_count", "text", "extracted_at", "error"])

    df = pd.DataFrame(all_results)

    # Deduplicate by title across all queries
    df = df.drop_duplicates(subset=["title"])

    # Parse published_at into a proper datetime
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")

    # Hour filter
    if since_hours is not None:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=since_hours)
        df = df[df["published_at"] >= cutoff]

    df = df.reset_index(drop=True)
    return df