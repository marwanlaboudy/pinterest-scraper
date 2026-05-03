import sys
import os
import re
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

query = sys.argv[1]

IS_CI = os.getenv("GITHUB_ACTIONS") == "true"
WAIT = 12000 if IS_CI else 5000


def dismiss_modal(page):
    try:
        close = page.locator("[data-test-id='fullPageSignupModal'] [aria-label='Close']")
        if close.is_visible(timeout=3000):
            close.click()
            page.wait_for_timeout(1000)
    except:
        pass


def goto_with_retry(page, url, retries=3):
    for _ in range(retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            return True
        except:
            page.wait_for_timeout(2000)
    return False


# ✅ group URLs and extract best video + audio
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


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        # ✅ FIXED VIEWPORT (matches VS behavior)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0"
        )

        page = context.new_page()

        search_url = f"https://www.pinterest.com/search/videos/?q={query.replace(' ', '+')}"
        goto_with_retry(page, search_url)

        page.wait_for_timeout(WAIT)
        dismiss_modal(page)

        # small scroll just to ensure loading
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(3000)

        pins = page.locator("div[data-test-id='pin']")
        pins.first.wait_for(timeout=20000)

        visible_pins = []
        for i in range(pins.count()):
            try:
                box = pins.nth(i).bounding_box()
                if box and 0 < box["y"] < 600:
                    visible_pins.append(pins.nth(i))
            except:
                continue

        # ✅ take more pins for reliability in CI
        top_pins = visible_pins[:6]

        found_video = None
        found_audio = None

        for pin in top_pins:
            collected_m3u8 = []

            def handle_response(resp):
                if ".m3u8" in resp.url:
                    collected_m3u8.append(resp.url)

            # attach listener fresh each loop
            page.on("response", handle_response)

            try:
                href = pin.locator("a").first.get_attribute("href")
                if not href:
                    continue

                pin_url = f"https://www.pinterest.com{href}"

                if not goto_with_retry(page, pin_url):
                    continue

                # force video load
                page.mouse.move(300, 400)
                page.mouse.wheel(0, 300)
                page.wait_for_timeout(6000)

                video_url, audio_url = pick_video_and_audio(collected_m3u8)

                if video_url:
                    found_video = video_url
                    found_audio = audio_url
                    break

            except:
                continue

        browser.close()

        if not found_video:
            print("No video found in first pins")
            sys.exit(1)

        print("Video:", found_video)
        print("Audio:", found_audio)

        create_button_png()

        # ✅ FFMPEG MERGE (with fallback)
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

        os.system(cmd)

        print("Saved as output.mp4")


if __name__ == "__main__":
    run()
