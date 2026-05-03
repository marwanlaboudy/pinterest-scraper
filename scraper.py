import sys
import os
import re
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

query = sys.argv[1]

IS_CI = os.getenv("GITHUB_ACTIONS") == "true"
WAIT = 12000 if IS_CI else 5000


def log(msg):
    print(msg, flush=True)


def dismiss_modal(page):
    try:
        close = page.locator("[data-test-id='fullPageSignupModal'] [aria-label='Close']")
        if close.is_visible(timeout=3000):
            close.click()
            page.wait_for_timeout(1000)
            log("Closed signup modal")
    except:
        pass


def goto_with_retry(page, url, retries=3):
    for attempt in range(retries):
        try:
            log(f"Navigating to: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            return True
        except Exception as e:
            log(f"Goto failed attempt {attempt+1}: {e}")
            page.wait_for_timeout(2000)
    return False


# 🔥 group + pick best video + audio
def pick_video_and_audio(urls):
    groups = {}

    for u in urls:
        m = re.search(r'/([a-f0-9]{32})', u)
        if m:
            vid = m.group(1)
            groups.setdefault(vid, []).append(u)

    if not groups:
        return None, None

    group = list(groups.values())[0]

    video_url = None
    audio_url = None

    for q in ["_720w", "_540w", "_480w", "_360w", "_240w"]:
        for u in group:
            if q in u:
                video_url = u
                break
        if video_url:
            break

    if not video_url:
        for u in group:
            if "_audio" not in u:
                video_url = u
                break

    for u in group:
        if "_audio" in u:
            audio_url = u
            break

    return video_url, audio_url


def create_button_png(path="shop_now_btn.png"):
    img = Image.new("RGBA", (340, 90), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([0, 0, 339, 89], radius=45, fill=(255, 255, 255, 255))
    draw.rounded_rectangle([0, 0, 339, 89], radius=45, outline=(30, 30, 30, 255), width=3)

    font = ImageFont.load_default()
    text = "SHOP NOW"

    bbox = draw.textbbox((0, 0), text, font=font)
    x = (340 - (bbox[2] - bbox[0])) // 2
    y = (90 - (bbox[3] - bbox[1])) // 2

    draw.text((x, y), text, fill=(30, 30, 30, 255), font=font)
    img.save(path)
    log("Created CTA button image")


def run():
    with sync_playwright() as p:
        log("Launching browser...")

        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0"
        )

        page = context.new_page()

        search_url = f"https://www.pinterest.com/search/videos/?q={query.replace(' ', '+')}"
        goto_with_retry(page, search_url)

        log("Waiting for initial load...")
        page.wait_for_timeout(WAIT)

        dismiss_modal(page)

        log("Scrolling page slightly...")
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(3000)

        pins = page.locator("div[data-test-id='pin']")
        pins.first.wait_for(timeout=20000)

        total = pins.count()
        log(f"Total pins found: {total}")

        visible_pins = []
        for i in range(total):
            try:
                box = pins.nth(i).bounding_box()
                if box:
                    log(f"Pin {i} Y: {box['y']}")
                if box and 0 < box["y"] < 600:
                    visible_pins.append(pins.nth(i))
            except:
                continue

        log(f"Visible pins: {len(visible_pins)}")

        top_pins = visible_pins[:6]
        log(f"Checking {len(top_pins)} pins...")

        found_video = None
        found_audio = None

        for i, pin in enumerate(top_pins):
            log(f"\n--- PIN {i+1} ---")

            collected_m3u8 = []

            def handle_response(resp):
                if ".m3u8" in resp.url:
                    log(f"Detected stream: {resp.url}")
                    collected_m3u8.append(resp.url)

            page.on("response", handle_response)

            try:
                href = pin.locator("a").first.get_attribute("href")
                if not href:
                    log("No href found")
                    continue

                pin_url = f"https://www.pinterest.com{href}"
                log(f"Opening pin: {pin_url}")

                if not goto_with_retry(page, pin_url):
                    continue

                log("Forcing video load...")
                page.mouse.move(300, 400)
                page.mouse.wheel(0, 300)
                page.wait_for_timeout(6000)

                log(f"Collected {len(collected_m3u8)} streams")

                video_url, audio_url = pick_video_and_audio(collected_m3u8)

                log(f"Selected video: {video_url}")
                log(f"Selected audio: {audio_url}")

                if video_url:
                    found_video = video_url
                    found_audio = audio_url
                    break

            except Exception as e:
                log(f"Error: {e}")
                continue

        browser.close()

        if not found_video:
            log("No video found in pins")
            sys.exit(1)

        log(f"FINAL VIDEO: {found_video}")
        log(f"FINAL AUDIO: {found_audio}")

        create_button_png()

        log("Running ffmpeg...")

        if found_audio:
            cmd = (
                f'ffmpeg -y '
                f'-i "{found_video}" '
                f'-i "{found_audio}" '
                f'-i "shop_now_btn.png" '
                f'-filter_complex '
                f'"[0:v]scale=720:1280[bg];[bg][2:v]overlay=(W-w)/2:H-220" '
                f'-c:v libx264 -preset fast '
                f'-c:a aac -shortest output.mp4'
            )
        else:
            cmd = (
                f'ffmpeg -y '
                f'-i "{found_video}" '
                f'-i "shop_now_btn.png" '
                f'-f lavfi -i anullsrc=r=44100:cl=stereo '
                f'-filter_complex '
                f'"[0:v]scale=720:1280[bg];[bg][1:v]overlay=(W-w)/2:H-220" '
                f'-c:v libx264 -preset fast '
                f'-c:a aac -shortest output.mp4'
            )

        log(f"FFmpeg command:\n{cmd}")

        os.system(cmd)

        if os.path.exists("output.mp4"):
            log("Saved as output.mp4")
        else:
            log("FFmpeg failed")
            sys.exit(1)


if __name__ == "__main__":
    run()
