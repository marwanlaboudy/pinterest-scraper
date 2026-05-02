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
        page.wait_for_timeout(5000)

        print("Searching:", query)
        search_box = page.locator("#search-input")
        search_box.wait_for(timeout=20000)
        search_box.click()
        human_type(page, query)
        page.keyboard.press("Enter")

        page.wait_for_timeout(5000)

        page.mouse.wheel(0, -10000)
        page.wait_for_timeout(2000)

        stream = {"url": None}

        def handle_response(resp):
            url = resp.url
            if "_720w.m3u8" in url:
                print("Found stream:", url)
                stream["url"] = url

        page.on("response", handle_response)

        pins = page.locator("div[data-test-id='pin']:visible")
        pins.first.wait_for(timeout=20000)
        pins.first.click()

        for _ in range(10):
            if stream["url"]:
                break
            page.wait_for_timeout(1000)

        browser.close()

        if not stream["url"]:
            print("No video found")
            return

        print("Downloading video...")
        os.system(f'ffmpeg -y -i "{stream["url"]}" -c copy output.mp4')

        print("Saved as output.mp4")

if __name__ == "__main__":
    run()
