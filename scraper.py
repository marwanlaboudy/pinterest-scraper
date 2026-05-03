import sys
import os
import re
import requests
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

query = sys.argv[1]
product_title = sys.argv[2] if len(sys.argv) > 2 else query
WAIT = 8000

FONT_PATH = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"


def log(msg):
    print(msg, flush=True)


# 🔥 NEW: status writer
def write_status(status):
    with open("status.txt", "w") as f:
        f.write(status)


def dismiss_modal(page):
    try:
        close = page.locator("[data-test-id='fullPageSignupModal'] [aria-label='Close']")
        if close.is_visible(timeout=3000):
            close.click()
            page.wait_for_timeout(1000)
    except:
        pass


def close_filters(page):
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        page.mouse.click(640, 300)
        page.wait_for_timeout(800)
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


def create_button_png(path="shop_now_btn.png"):
    W, H = 500, 110
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([0, 0, W-1, H-1], radius=55, fill=(255, 255, 255, 245))
    draw.rounded_rectangle([0, 0, W-1, H-1], radius=55, outline=(20, 20, 20, 255), width=4)

    try:
        font = ImageFont.truetype(FONT_PATH, size=48)
    except:
        font = ImageFont.load_default()

    text = "SHOP NOW"
    bbox = draw.textbbox((0, 0), text, font=font)

    x = (W - (bbox[2] - bbox[0])) // 2
    y = (H - (bbox[3] - bbox[1])) // 2

    draw.text((x, y), text, fill=(20, 20, 20, 255), font=font)
    img.save(path)


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        page = context.new_page()

        search_url = f"https://www.pinterest.com/search/videos/?q={query.replace(' ', '+')}"
        goto_with_retry(page, search_url)

        page.wait_for_timeout(WAIT)

        dismiss_modal(page)
        close_filters(page)

        pins = page.locator("div[data-test-id='pin']")
        pins.first.wait_for(timeout=20000)

        found_video = None

        for i in range(min(10, pins.count())):
            try:
                href = pins.nth(i).locator("a").first.get_attribute("href")
                if not href:
                    continue

                page.goto(f"https://www.pinterest.com{href}")
                page.wait_for_timeout(3000)

                content = page.content()

                match = re.search(r'(https://[^"]+\.m3u8)', content)
                if match:
                    found_video = match.group(1)
                    break

            except:
                continue

        browser.close()

        # ❌ NO VIDEO FOUND
        if not found_video:
            log("No video found")
            write_status("NOT_FOUND")
            return

        # ✅ VIDEO FOUND
        log("Video found")

        create_button_png()

        cmd = (
            f'ffmpeg -y -i "{found_video}" -i shop_now_btn.png '
            f'-filter_complex "[0:v]scale=720:1280:force_original_aspect_ratio=decrease,'
            f'pad=720:1280:(ow-iw)/2:(oh-ih)/2[bg];'
            f'[bg][1:v]overlay=(W-w)/2:H-160[out]" '
            f'-map "[out]" -c:v libx264 -preset fast -crf 18 output.mp4'
        )

        os.system(cmd)

        # ✅ SUCCESS / FAIL
        if os.path.exists("output.mp4"):
            log("Saved output.mp4")
            write_status("FOUND")
        else:
            log("FFmpeg failed")
            write_status("FAILED")


if __name__ == "__main__":
    run()
