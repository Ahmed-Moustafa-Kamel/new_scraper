"""
test_almasry_rss.py
-------------------
Test almasryalyoum's own RSS feed and filter for articles about 'orange'.

Run:
    python test_almasry_rss.py
"""

import feedparser
import re

KEYWORD = "orange"   # change to any keyword you want

# almasryalyoum RSS feeds to try
RSS_FEEDS = [
    "https://www.almasryalyoum.com/rss/rss.aspx",
    "https://www.almasryalyoum.com/rss/rss.aspx?sec=2",   # economy section
    "https://www.almasryalyoum.com/rss/rss.aspx?sec=4",   # tech section
]

def search_feed(feed_url, keyword):
    print(f"\n📡 Fetching: {feed_url}")
    feed = feedparser.parse(feed_url)

    if not feed.entries:
        print(f"  ❌ No entries found (feed may be blocked or empty)")
        return []

    print(f"  ✅ Total entries in feed: {len(feed.entries)}")

    # Filter by keyword in title or summary
    matched = []
    for entry in feed.entries:
        title   = entry.get("title", "")
        summary = entry.get("summary", "")
        link    = entry.get("link", "")
        date    = entry.get("published", "")

        if re.search(keyword, title + summary, re.IGNORECASE):
            matched.append({
                "title":   title,
                "link":    link,
                "date":    date,
                "summary": summary[:150],
            })

    print(f"  🎯 Articles matching '{keyword}': {len(matched)}")
    return matched


def main():
    print("=" * 60)
    print(f"Testing almasryalyoum RSS | keyword: '{KEYWORD}'")
    print("=" * 60)

    all_matched = []
    for feed_url in RSS_FEEDS:
        results = search_feed(feed_url, KEYWORD)
        all_matched.extend(results)

    # Deduplicate by link
    seen  = set()
    unique = []
    for art in all_matched:
        if art["link"] not in seen:
            seen.add(art["link"])
            unique.append(art)

    print(f"\n{'='*60}")
    print(f"Total unique matched articles: {len(unique)}\n")

    for i, art in enumerate(unique, 1):
        print(f"[{i}] {art['title']}")
        print(f"     Date    : {art['date']}")
        print(f"     URL     : {art['link']}")
        print(f"     Preview : {art['summary'][:120]}")
        print()

    if not unique:
        print("❌ No matches found.")
        print("   Either the RSS is blocked from AWS,")
        print("   or no recent articles mention the keyword.")

if __name__ == "__main__":
    main()