"""
test_stealth.py
---------------
Test if playwright-stealth 1.0.6 bypasses Cloudflare on almasryalyoum.

Run:
    python test_stealth.py
"""

from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
import re

URL     = "https://www.almasryalyoum.com/news/search/?keyword=orange"
PATTERN = re.compile(r"/news/details/\d+")

def main():
    print(f"Testing: {URL}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ar-EG",
            viewport={"width": 1280, "height": 800},
        )

        page = context.new_page()

        # Apply stealth
        stealth_sync(page)

        print("Loading page...")
        try:
            page.goto(URL, timeout=60000, wait_until="load")
        except Exception as e:
            print(f"❌ Error: {e}")
            browser.close()
            return

        # Wait for JS to finish
        page.wait_for_timeout(5000)

        title = page.title()
        print(f"Page title: {title}")
        print(f"Final URL : {page.url}\n")

        if "moment" in title.lower() or "لحظة" in title or "cloudflare" in title.lower():
            print("❌ Still blocked by Cloudflare — stealth didn't work")
        else:
            print("✅ Cloudflare bypassed!\n")

            # Find article links
            links     = page.locator("a")
            count     = links.count()
            matched   = []

            for i in range(count):
                href = links.nth(i).get_attribute("href")
                if href and PATTERN.search(href):
                    if href.startswith("/"):
                        href = f"https://www.almasryalyoum.com{href}"
                    matched.append(href)

            print(f"Total links on page : {count}")
            print(f"Article links found : {len(matched)}\n")

            for lnk in matched[:10]:
                print(f"  ✅ {lnk}")

        context.close()
        browser.close()

if __name__ == "__main__":
    main()


