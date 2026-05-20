import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

def test_almasry():
    query = "vodafone"
    url = f"https://www.almasryalyoum.com/news/search/?keyword={quote(query, safe='')}"
    # Changed pattern to match both relative paths and absolute domains
    pattern = r"/news/details/\d+"

    print(f"Testing URL: {url}\n")

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print("Loading page...")
        try:
            page.goto(url, timeout=60000)
            
            # Wait for the search layout/results block to load in DOM
            print("Waiting for search results structure...")
            page.wait_for_selector(".search-result, .news-list, body", timeout=15000)
            
            # Scroll down slightly to trigger lazy-loaded elements
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 4)")
            page.wait_for_timeout(4000)

            print(f"✅ Page title: {page.title()}")
            print(f"\n📄 Page URL after load: {page.url}")
            
            # Check all links on the page
            links = page.locator("a")
            total_links = links.count()
            print(f"Total links found on page: {total_links}")

            print("\n🎯 Links matching pattern:")
            matched = 0
            unique_links = set()

            for i in range(total_links):
                href = links.nth(i).get_attribute("href")
                if href and re.search(pattern, href):
                    if href not in unique_links:
                        unique_links.add(href)
                        print(f"  ✅ {href}")
                        matched += 1

            print(f"\nTotal unique matched articles: {matched}")

            if matched == 0 and total_links > 0:
                print("\n⚠️ Found links, but none matched the pattern.")
                print("Printing sample links to check structure changes:")
                for i in range(min(15, total_links)):
                    sample_href = links.nth(i).get_attribute("href")
                    if sample_href:
                        print(f"  - {sample_href}")

        except Exception as e:
            print(f"TIMEOUT or ERROR: {e}")
        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    test_almasry()