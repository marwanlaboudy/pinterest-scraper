import sys
import random
import os
from playwright.sync_api import sync_playwright

query = sys.argv[1]

IS_CI = os.getenv("GITHUB_ACTIONS") == "true"
WAIT = 10000 if IS_CI else 4000

def human_type(page, text):
    for char in text:
        page.keyboard.type(char, delay=random.randint(50, 120))

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1280,800",
            ]
        )

        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )

        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        print("Opening Pinterest...")
        page.goto("https://www.pinterest.com/ideas/", wait_until="domcontentloaded")
        page.wait_for_timeout(WAIT)

        # SEARCH
        print("Searching:", query)
        search_box = page.locator("#search-input")
        search_box.wait_for(timeout=20000)
        search_box.click()
        human_type(page, query)
        page.keyboard.press("Enter")
        page.wait_for_timeout(WAIT)

        # save search URL after search completes
        search_url = page.url
        print("Search URL:", search_url)

        # scroll to top
        page.mouse.wheel(0, -10000)
        page.wait_for_timeout(2000)

        # capture video stream
        stream = {"url": None}

        def handle_response(resp):
            url = resp.url
            if "_720w.m3u8" in url:
                print("Found stream:", url)
                stream["url"] = url

        page.on("response", handle_response)

        # get pin hrefs first — collect all links before clicking anything
        pins = page.locator("div[data-test-id='pin']:visible a")
        pins.first.wait_for(timeout=20000)
        count = pins.count()
        print(f"Found {count} pins")

        # collect all pin URLs upfront so we never deal with stale locators
        pin_urls = []
        for i in range(min(count, 10)):
            try:
                href = pins.nth(i).get_attribute("href")
                if href:
                    full_url = f"https://www.pinterest.com{href}" if href.startswith("/") else href
                    pin_urls.append(full_url)
            except Exception:
                continue

        print(f"Collected {len(pin_urls)} pin URLs")

        for i, pin_url in enumerate(pin_urls):
            print(f"Trying pin {i+1}: {pin_url}")

            try:
                # navigate directly to pin instead of clicking
                page.goto(pin_url, wait_until="domcontentloaded")
                page.wait_for_timeout(6000)
            except Exception as e:
                print(f"Could not open pin {i+1}: {e}")
            
            for _ in range(8):
                if stream["url"]:
                    break
                page.wait_for_timeout(1000)

            if stream["url"]:
                print("Video found!")
                break

            # go back to search results by navigating directly to saved URL
            print("No stream, going back to search...")
            page.goto(search_url, wait_until="domcontentloaded")
            page.wait_for_timeout(WAIT)

        browser.close()

        if not stream["url"]:
            print("No video found after trying multiple pins")
            sys.exit(1)

        print("Downloading video...")
        os.system(f'ffmpeg -y -i "{stream["url"]}" -c copy output.mp4')

        if os.path.exists("output.mp4"):
            print("Saved as output.mp4")
        else:
            print("Download failed")
            sys.exit(1)

if __name__ == "__main__":
    run()
