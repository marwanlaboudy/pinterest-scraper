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

        # load saved session if it exists
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

        # open video search directly
        video_search_url = f"https://www.pinterest.com/search/videos/?q={query.replace(' ', '+')}"
        print("Opening video search:", video_search_url)
        goto_with_retry(page, video_search_url)
        page.wait_for_timeout(WAIT)

        dismiss_modal(page)

        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(3000)

        # collect pin URLs
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

        print(f"Collected {len(pin_urls)} pin URLs")

        # capture m3u8 from network
        collected_m3u8 = []

        def handle_response(resp):
            url = resp.url
            if ".m3u8" in url:
                collected_m3u8.append(url)
                print("Seen m3u8:", url)

        page.on("response", handle_response)

        found_url = None

        for i, pin_url in enumerate(pin_urls):
            print(f"Trying pin {i+1}: {pin_url}")

            collected_m3u8.clear()

            ok = goto_with_retry(page, pin_url)
            if not ok:
                print(f"Could not open pin {i+1}, skipping...")
                continue

            page.wait_for_timeout(6000)

            # try network first
            if collected_m3u8:
                best = pick_best_m3u8(collected_m3u8)
                if best:
                    print("Picked stream (network):", best)
                    found_url = best
                    break

            # try page source
            src = extract_from_page_source(page)
            if src:
                found_url = src
                break

            # try DOM video element
            try:
                video_src = page.evaluate("""() => {
                    const v = document.querySelector('video');
                    return v ? (v.currentSrc || v.src) : null;
                }""")
                if video_src and not video_src.startswith("blob"):
                    print("Picked stream (DOM):", video_src)
                    found_url = video_src
                    break
                else:
                    print("No usable stream found, trying next pin...")
            except Exception:
                pass

        browser.close()

        if not found_url:
            print("No video found after trying all pins")
            sys.exit(1)

        print("Downloading and compressing video...")
        os.system(
            f'ffmpeg -y '
            f'-i "{found_url}" '
            f'-f lavfi -i anullsrc=r=44100:cl=stereo '
            f'-t 15 '
            f'-vf "scale=720:1280" '
            f'-r 25 '
            f'-pix_fmt yuv420p '
            f'-c:v libx264 '
            f'-profile:v baseline '
            f'-level 3.0 '
            f'-crf 28 '
            f'-preset fast '
            f'-c:a aac '
            f'-ar 44100 '
            f'-b:a 128k '
            f'-shortest '
            f'-movflags +faststart '
            f'output.mp4'
        )

        if os.path.exists("output.mp4"):
            size_mb = os.path.getsize("output.mp4") / (1024 * 1024)
            print(f"Video size: {size_mb:.1f} MB")
            print("Saved as output.mp4")
        else:
            print("Download failed")
            sys.exit(1)

if __name__ == "__main__":
    run()
