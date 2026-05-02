import sys
import random
import os
import re
from playwright.sync_api import sync_playwright

query = sys.argv[1]

IS_CI = os.getenv("GITHUB_ACTIONS") == "true"
WAIT = 10000 if IS_CI else 4000

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

def goto_with_retry(page, url, retries=3, timeout=60000):
    for attempt in range(retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except Exception as e:
            print(f"Goto attempt {attempt+1} failed: {e}")
            page.wait_for_timeout(3000)
    return False

def pick_best_m3u8(urls):
    if not urls:
        return None
    for u in urls:
        if "_720w" in u:
            return u
    def score(u):
        m = re.search(r"_(\d+)w\.m3u8", u)
        return int(m.group(1)) if m else 0
    return sorted(urls, key=score, reverse=True)[0]

def extract_from_page_source(page):
    try:
        content = page.content()
        matches = re.findall(r'https://v1\.pinimg\.com/videos/[^"\']+\.m3u8', content)
        if matches:
            print(f"Found m3u8 in page source: {matches[0]}")
            return matches[0]
    except Exception as e:
        print(f"Page source extraction failed: {e}")
    return None

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

        session_file = "pinterest_session.json"
        if os.path.exists(session_file):
            print("Loading saved Pinterest session...")
            context = browser.new_context(
                storage_state=session_file,
                user_agent="Mozilla/5.0",
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/New_York",
            )
        else:
            print("No session found, starting fresh...")
            context = browser.new_context(
                user_agent="Mozilla/5.0",
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

        video_search_url = f"https://www.pinterest.com/search/videos/?q={query.replace(' ', '+')}"
        print("Opening video search:", video_search_url)
        goto_with_retry(page, video_search_url)
        page.wait_for_timeout(WAIT)

        dismiss_modal(page)

        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(3000)

        pins = page.locator("div[data-test-id='pin']:visible a")
        pins.first.wait_for(timeout=20000)

        count = min(pins.count(), 20)
        print(f"Found {count} video pins")

        seen = set()
        pin_urls = []
        for i in range(count):
            try:
                href = pins.nth(i).get_attribute("href")
                if href:
                    full = f"https://www.pinterest.com{href}" if href.startswith("/") else href
                    if full not in seen:
                        seen.add(full)
                        pin_urls.append(full)
            except Exception:
                continue

        if not pin_urls:
            print("No pins found")
            browser.close()
            sys.exit(1)

        collected_m3u8 = []

        def handle_response(resp):
            if ".m3u8" in resp.url:
                collected_m3u8.append(resp.url)

        page.on("response", handle_response)

        found_url = None

        for pin_url in pin_urls:
            collected_m3u8.clear()

            if not goto_with_retry(page, pin_url):
                continue

            page.wait_for_timeout(6000)

            if collected_m3u8:
                found_url = pick_best_m3u8(collected_m3u8)
                break

            src = extract_from_page_source(page)
            if src:
                found_url = src
                break

        browser.close()

        if not found_url:
            print("No video found")
            sys.exit(1)

        print("Downloading + adding CTA...")

        os.system(
            f'ffmpeg -y '
            f'-i "{found_url}" '
            f'-f lavfi -i anullsrc=r=44100:cl=stereo '
            f'-t 15 '
            f'-vf "scale=720:1280,'
            f'drawtext=text=\'SHOP NOW\':'
            f'fontcolor=white:fontsize=60:'
            f'x=(w-text_w)/2:y=h-250:'
            f'box=1:boxcolor=0x000000AA:boxborderw=20" '
            f'-r 25 '
            f'-pix_fmt yuv420p '
            f'-c:v libx264 '
            f'-preset fast '
            f'-c:a aac '
            f'-b:a 128k '
            f'-shortest '
            f'output.mp4'
        )

        if os.path.exists("output.mp4"):
            print("Saved as output.mp4")
        else:
            print("Failed")
            sys.exit(1)

if __name__ == "__main__":
    run()
