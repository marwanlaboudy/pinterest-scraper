import sys
import random
import os
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
    except:
        pass

    try:
        page.keyboard.press("Escape")
        print("Closed modal via Escape")
        page.wait_for_timeout(1000)
    except:
        pass

    try:
        page.mouse.click(10, 10)
        print("Closed modal by clicking outside")
        page.wait_for_timeout(1000)
    except:
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

def build_video_url(query):
    return f"https://www.pinterest.com/search/videos/?q={query.replace(' ', '+')}"

def pick_best_m3u8(urls):
    # prefer 720w, else highest width found
    if not urls:
        return None
    for u in urls:
        if "_720w" in u:
            return u
    # fallback: sort by width suffix if present
    def score(u):
        import re
        m = re.search(r"_(\d+)w\.m3u8", u)
        return int(m.group(1)) if m else 0
    return sorted(urls, key=score, reverse=True)[0]

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

        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
        )

        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # 🔥 Open video search page directly
        video_url = build_video_url(query)
        print("Opening video search:", video_url)
        goto_with_retry(page, video_url)
        page.wait_for_timeout(WAIT)

        dismiss_modal(page)

        # load a bit more
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(3000)

        # 🧠 collect first 20 pins (deduped)
        pins = page.locator("div[data-test-id='pin']:visible a")
        pins.first.wait_for(timeout=20000)

        count = min(pins.count(), 20)
        print(f"Found {count} video pins")

        seen = set()
        video_urls = []
        for i in range(count):
            try:
                href = pins.nth(i).get_attribute("href")
                if href:
                    full = f"https://www.pinterest.com{href}" if href.startswith("/") else href
                    if full not in seen:
                        seen.add(full)
                        video_urls.append(full)
            except:
                continue

        if not video_urls:
            print("No videos found")
            browser.close()
            sys.exit(1)

        # 🔁 randomize order
        random.shuffle(video_urls)

        # 🎯 network capture (collect ALL m3u8 for a page)
        collected_m3u8 = []

        def handle_response(resp):
            url = resp.url
            if ".m3u8" in url:
                collected_m3u8.append(url)
                print("Seen m3u8:", url)

        page.on("response", handle_response)

        found_url = None

        # 🔁 try each candidate until we get a usable stream
        for i, chosen_url in enumerate(video_urls):
            print(f"Trying video {i+1}: {chosen_url}")

            collected_m3u8.clear()

            ok = goto_with_retry(page, chosen_url)
            if not ok:
                continue

            page.wait_for_timeout(6000)

            # 1) pick from network if any
            if collected_m3u8:
                best = pick_best_m3u8(collected_m3u8)
                if best:
                    print("Picked stream (network):", best)
                    found_url = best
                    break

            # 2) fallback: DOM video src
            video_src = page.evaluate("""
            () => {
                const v = document.querySelector("video");
                return v ? (v.currentSrc || v.src) : null;
            }
            """)
            if video_src:
                print("Found video element:", video_src)
                if not video_src.startswith("blob"):
                    found_url = video_src
                    print("Picked stream (DOM):", found_url)
                    break
                else:
                    print("Blob video detected, skipping...")

        browser.close()

        if not found_url:
            print("No working video found after trying all")
            sys.exit(1)

        # 🎬 DOWNLOAD (your original style)
        print("Downloading video...")
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
            print("Saved as output.mp4")
        else:
            print("Download failed")
            sys.exit(1)

if __name__ == "__main__":
    run()
