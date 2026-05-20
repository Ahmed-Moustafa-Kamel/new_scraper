import re
import os
from urllib.parse import urljoin, quote, unquote
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import pandas as pd

websites = {
    "youm7": {"base_url": "https://www.youm7.com/Home/Search?allwords=", "pattern": r"/story/", "tier": "tier1"},
    "almasryalyoum": {"base_url": "https://www.almasryalyoum.com/news/search/?keyword=", "pattern": r"/news/details/\d+", "tier": "tier1"},
    "elwafd": {"base_url": "https://alwafd.news/search/term?w=", "pattern": r"/\d{6,}", "tier": "tier1"},
    "dostor": {"base_url": "https://www.dostor.org/search/term?w=", "pattern": r"/\d{6,}", "tier": "tier1"},
    "ahram_english": {"base_url": "https://english.ahram.org.eg/UI/Front/Search.aspx?Text=", "pattern": r"/NewsContent/\d+/\d+/\d+/", "tier": "tier1"},
    "akhbarelyom": {"base_url": "https://akhbarelyom.com/News/Search/1?JournalID=1&query=", "pattern": r"/news/newdetails/\d+/", "tier": "tier1"},
    "vetogate": {"base_url": "https://www.vetogate.com/search/term?w=", "pattern": r"/\d{6,}", "tier": "tier1"},
    "almalnews": {"base_url": "https://almalnews.com/searchnews/", "pattern": r"/\d{6,}/", "tier": "tier1"},
    "rosaelyoussef": {"base_url": "https://www.rosaelyoussef.com/search/term?w=", "pattern": r"/\d{6,}", "tier": "tier1"},
    "daily_rosaelyoussef": {"base_url": "https://daily.rosaelyoussef.com/Search?q=", "pattern": r"/\d{6,}/", "tier": "tier1"},
    "alalamelyoum": {"base_url": "https://alalamelyoum.co/?s=", "pattern": r"/\d{6,}/", "tier": "tier1"},
    "almessa_gomhuria": {"base_url": "https://almessa.gomhuriaonline.com/?s=", "pattern": r"/\d{6,}/", "tier": "tier1"},
    "egyptian_gazette": {"base_url": "https://egyptian-gazette.com/?s=", "pattern": r"/technology/[a-z0-9-]+", "tier": "tier1"},
    "cairo24": {"base_url": "https://www.cairo24.com/search/term?w=", "pattern": r"/\d{6,}", "tier": "tier1"},
    "ictbusiness": {"base_url": "https://ictbusiness.org/?s=", "pattern": r"/[^\s/]{10,}", "tier": "tier1"},
    "techknowledge": {"base_url": "https://techknowledge.news/?search_in=all&s=", "pattern": r"/[^\s/]{10,}", "tier": "tier1"},
    "techrevieweg": {"base_url": "https://techrevieweg.com/?s=", "pattern": r"/[a-z0-9-]{5,}/", "tier": "tier1"},
    "capitalnewseg": {"base_url": "https://capitalnewseg.com/?s=", "pattern": r"/\d{6,}/", "tier": "tier1"},
    "fintechgate": {"base_url": "https://fintechgate.net/?s=", "pattern": r"/\d{4}/\d{2}/\d{2}/", "tier": "tier1"},
    "egypttelegraph": {"base_url": "https://www.egypttelegraph.com/searchnews/", "pattern": r"/article/\d+/", "tier": "tier1"},
    "besraha": {"base_url": "https://besraha.com/search/term?search=", "pattern": r"/\d{5,}", "tier": "tier1"},
    "shorouknews": {"base_url": "https://www.shorouknews.com/search/default.aspx?q=", "pattern": r"/news/view\.aspx\?cdate=\d+&id=", "tier": "tier1"},
    "elfagr": {"base_url": "https://www.elfagr.org/search/term?w=", "pattern": r"/\d{6,}", "tier": "tier1"},
    "albawabhnews": {"base_url": "https://www.albawabhnews.com/search/term?w=", "pattern": r"/\d{6,}", "tier": "tier1"},
    "masrawy": {"base_url": "https://www.masrawy.com/search/0/", "pattern": r"/details/\d{4}/\d+/\d+/\d+/", "tier": "tier1"},
    "elwatannews": {"base_url": "https://www.elwatannews.com/search/news/", "pattern": r"/news/details/\d+", "tier": "tier1"},
    "elbalad": {"base_url": "https://www.elbalad.news/search/term?w=", "pattern": r"/\d{6,}", "tier": "tier1"},
    "amwalalghad": {"base_url": "https://amwalalghad.com/?s=", "pattern": r"/\d{4}/\d{2}/\d{2}/", "tier": "tier1"},
    "egypttoday": {"base_url": "https://www.egypttoday.com/Article/Search?title=", "pattern": r"/Article/\d+/\d+/", "tier": "tier1"},
    "hapijournal": {"base_url": "https://hapijournal.com/?s=", "pattern": r"/\d{4}/\d{2}/\d{2}/", "tier": "tier1"}
}

def scrape_links(queries, max_workers: int = 2) -> pd.DataFrame:
    if isinstance(queries, str):
        queries = [queries]

    all_rows = []
    print(f"🚀 [INIT] Starting optimized scraper for {len(queries)} queries...")

    # Assets that slow us down but won't trigger bot detectors when blocked
    SAFE_BLOCKED_RESOURCES = ["image", "media", "font", "stylesheet"]

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        for query in queries:
            print(f"\n🔍 --- Processing Query Target: '{query}' ---")
            for site, config in websites.items():
                url = f"{config['base_url']}{quote(query, safe='')}"
                
                print(f"  → Connecting to {site}...", end="", flush=True)
                page = context.new_page()

                # Optimized routing engine
                def handle_route(route):
                    if route.request.resource_type in SAFE_BLOCKED_RESOURCES:
                        return route.abort()
                    return route.continue_()

                page.route("**/*", handle_route)
                found_links = set()

                try:
                    # 'domcontentloaded' means the core HTML structure is ready.
                    # We lower the timeout to 12 seconds so slow sites don't hijack our pipeline.
                    page.goto(url, wait_until="domcontentloaded", timeout=12000)
                    
                    # Quick 1-second grace period for trailing script nodes to execution-inject links
                    page.wait_for_timeout(1000)

                    links = page.locator("a")
                    link_count = links.count()

                    for i in range(link_count):
                        href = links.nth(i).get_attribute("href")
                        if href and re.search(config["pattern"], href):
                            if href.startswith("/"):
                                href = urljoin(page.url, href)
                            parsed = href.split("?", 1)
                            parsed[0] = quote(unquote(parsed[0]), safe="/:@")
                            href = "?".join(parsed)
                            found_links.add(href)

                    for link in found_links:
                        all_rows.append({
                            "query": query,
                            "site": site,
                            "tier": config["tier"],
                            "link": link,
                        })
                    
                    print(f" Success! (Found {len(found_links)} target links)")

                except Exception as e:
                    # Keep yourself informed if a site drops the connection or times out
                    print(f" Failed/Timed Out (Skipped)")
                finally:
                    page.close()

        context.close()
        browser.close()

    df = pd.DataFrame(all_rows, columns=["query", "site", "tier", "link"])
    df = df.drop_duplicates(subset="link").reset_index(drop=True)
    print(f"\n📊 [COMPLETE] Found {len(df)} total unique entries across all query matrices.")
    return df

if __name__ == "__main__":
    queries = ["orange", "فودافون", "اتصالات", "we"]
    df = scrape_links(queries)
    df.to_csv("scraped_links.csv", index=False, encoding="utf-8-sig")