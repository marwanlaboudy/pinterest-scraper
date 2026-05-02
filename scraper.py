import sys
import random
import os
from playwright.sync_api import sync_playwright

query = sys.argv[1]

def human_type(page, text):
    for char in text:
        page.keyboard.type(char, delay=random.randint(50, 120))

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()

        print("Opening Pinterest...")
        page.goto("https://www.pinterest.com/ideas/", wait_until="domcontentloaded")
        page.wait_for_timeout(8000)

        # 🔍 SEARCH
        print("Searching:", query)
        search_box = page.locator("#search-input")
        search_box.wait_for(timeout=20000)
        search_box.click()
        human_type(page, query)
        page.keyboard.press("Enter")

        page.wait_for_timeout(8000)

        # go to top
        page.mouse.wheel(0, -10000)
        page.wait_for_timeout(2000)

        # 🎯 capture video stream
        stream = {"url": None}

        def handle_response(resp):
            url = resp.url
            if "_720w.m3u8" in url:
                print("Found stream:", url)
                stream["url"] = url

        page.on("response", handle_response)

        # 🧠 TRY MULTIPLE PINS
        pins = page.locator("div[data-test-id='pin']:visible")
        pins.first.wait_for(timeout=20000)

        count = pins.count()
        print(f"Found {count} pins")

        for i in range(min(count, 10)):  # try first 10 pins
            print(f"Trying pin {i+1}")

            pins.nth(i).click()
            page.wait_for_timeout(5000)

            # wait for stream
            for _ in range(6):
                if stream["url"]:
                    break
                page.wait_for_timeout(1000)

            if stream["url"]:
                print("Video found!")
                break

            # go back if not video
            page.go_back()
            page.wait_for_timeout(3000)

        browser.close()

        # ❌ NO VIDEO
        if not stream["url"]:
            print("No video found after trying multiple pins")
            return

        # 🎬 DOWNLOAD VIDEO
        print("Downloading video...")
        os.system(f'ffmpeg -y -i "{stream["url"]}" -c copy output.mp4')

        if os.path.exists("output.mp4"):
            print("Saved as output.mp4")
        else:
            print("Download failed")

if __name__ == "__main__":
    run()
