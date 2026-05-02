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

def dismiss_modal(page):
    try:
        close = page.locator("[data-test-id='fullPageSignupModal'] [aria-label='Close']")
        if close.is_visible(timeout=3000):
            close.click()
            print("Closed modal via X button")
            page.wait_for_timeout(1000)
            return
    except Exception:
        pass

    try:
        page.keyboard.press("Escape")
        print("Closed modal via Escape")
        page.wait_for_timeout(1000)
    except Exception:
        pass

    try:
        page.mouse.click(10, 10)
        print("Closed modal by clicking outside")
        page.wait_for_timeout(1000)
    except Exception:
        pass

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

        # ✅ load saved session if it exists
        session_file = "pinterest_session.json"
        if os.path.exists(session_file):
            print("Loading saved Pinterest session...")
            context = browser.new_context(
                storage_state=session_file,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/New_York",
            )
        else:
            print("No session found, starting fresh...")
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/New_York",
            )
            context.add_cookies([{
                "name": "cpb",
                "value": "1",
                "domain": ".pinterest.com",
                "path": "/",
            }])

        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        print("Opening Pinterest...")
        page.goto("https://www.pinterest.com/ideas/", wait_until="domcontentloaded")
        page.wait_for_timeout(WAIT)

        dismiss_modal(page)

        print("Searching:", query)
        search_box = page.locator("#search-input")
        search_box.wait_for(timeout=20000)

        try:
            page.locator("[data-test-id='fullPageSignupModal']").wait_for(state="hidden", timeout=5000)
        except Exception:
            pass

        search_box.click()
        human_type(page, query)
        page.keyboard.press("Enter")
        page.wait_for_timeout(WAIT)

        search_url = page.url
        print("Search URL:", search_url)

        page.mouse.wheel(0, -10000)
        page.wait_for_timeout(2000)

        dismiss_modal(page)

        stream = {"url": None}

        def handle_response(resp):
            url = resp.url
            if "_720w.m3u8" in url:
                print("Found stream:", url)
                stream["url"] = url

        page.on("response", handle_response)

        pins = page.locator("div[data-test-id='pin']:visible a")
        pins.first.wait_for(timeout=20000)
        count = pins.count()
        print(f"Found {count} pins")

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

            print("No stream, going back to search...")
            page.goto(search_url, wait_until="domcontentloaded")
            page.wait_for_timeout(WAIT)
            dismiss_modal(page)

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
