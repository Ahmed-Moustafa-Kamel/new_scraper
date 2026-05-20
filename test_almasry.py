import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

def test_almasry():
    query = "vodafone"
    url = f"https://www.almasryalyoum.com/news/search/?keyword={quote(query, safe='')}"
    pattern = r"/news/details/\d+"

    print(f"Testing URL: {url}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Apply stealth to help handle Cloudflare challenges
        stealth_sync(page)

        print("Loading page...")
        try:
            page.goto(url, timeout=60000)
            # Wait extra time for JS/Cloudflare challenge to complete
            page.wait_for_timeout(5000)

            print(f"✅ Page title: {page.title()}")
            print(f"\n📄 Page URL after load: {page.url}")
            print(f"\n📝 Page content preview (first 1000 chars):")
            print(page.content()[:1000])
            print("\n" + "="*60 + "\n")

            # Check all links on the page
            links = page.locator("a")
            total_links = links.count()
            print(f"Total links on page: {total_links}")

            print("\n🔗 All links found (first 30):")
            for i in range(min(30, total_links)):
                href = links.nth(i).get_attribute("href")
                if href:
                    print(f"  {href}")

            print("\n🎯 Links matching pattern:")
            matched = 0
            for i in range(total_links):
                href = links.nth(i).get_attribute("href")
                if href and re.search(pattern, href):
                    print(f"  ✅ {href}")
                    matched += 1

            print(f"\nTotal matched: {matched}")

        except Exception as e:
            print(f"TIMEOUT or ERROR: {e}")
        finally:
            # Ensures browser safely closes even on failure
            context.close()
            browser.close()

if __name__ == "__main__":
    test_almasry()