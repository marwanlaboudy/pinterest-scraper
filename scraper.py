import sys
import random
import os
from playwright.sync_api import sync_playwright

query = sys.argv[1]

IS_CI = os.getenv("GITHUB_ACTIONS") == "true"
WAIT = 8000 if IS_CI else 4000

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

        # hide webdriver flag from Pinterest JS detection
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

        # get initial pin count
        pins = page.locator("div[data-test-id='pin']:visible")
        pins.first.wait_for(timeout=20000)
        count = pins.count()
        print(f"Found {count} pins")

        for i in range(min(count, 10)):
            print(f"Trying pin {i+1}")

            # re-query pins fresh every iteration to avoid stale locator
            pins = page.locator("div[data-test-id='pin']:visible")
            try:
                pins.nth(i).wait_for(timeout=10000)
                pins.nth(i).click()
            except Exception as e:
                print(f"Could not click pin {i+1}: {e}")
                continue

            page.wait_for_timeout(5000)

            for _ in range(8):
                if stream["url"]:
                    break
                page.wait_for_timeout(1000)

            if stream["url"]:
                print("Video found!")
                break

            # go back and wait for pins to reload
            page.go_back()
            page.wait_for_timeout(WAIT)

            # wait for pins to reappear before next iteration
            try:
                page.locator("div[data-test-id='pin']:visible").first.wait_for(timeout=15000)
            except Exception:
                print("Pins didn't reload in time, stopping.")
                break

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
