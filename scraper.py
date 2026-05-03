import sys
import os
import re
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

query = sys.argv[1]

IS_CI = os.getenv("GITHUB_ACTIONS") == "true"
WAIT = 10000 if IS_CI else 4000


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


def pick_best_m3u8(urls):
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
        return matches[0] if matches else None
    except:
        return None


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
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        search_url = f"https://www.pinterest.com/search/videos/?q={query.replace(' ', '+')}"
        goto_with_retry(page, search_url)

        page.wait_for_timeout(WAIT)
        dismiss_modal(page)

        # scroll to ensure pins load
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(3000)

        pins = page.locator("div[data-test-id='pin']")
        pins.first.wait_for(timeout=20000)

        # ✅ get visible pins (top viewport)
        visible_pins = []
        for i in range(pins.count()):
            try:
                box = pins.nth(i).bounding_box()
                if box and box["y"] < 800:
                    visible_pins.append(pins.nth(i))
            except:
                continue

        # ✅ first 4 visually
        top_pins = visible_pins[:4]

        found_url = None

        for pin in top_pins:
            collected_m3u8 = []

            def handle_response(resp):
                if ".m3u8" in resp.url:
                    collected_m3u8.append(resp.url)

            page.on("response", handle_response)

            try:
                href = pin.locator("a").get_attribute("href")
                if not href:
                    continue

                pin_url = f"https://www.pinterest.com{href}"

                if not goto_with_retry(page, pin_url):
                    continue

                # 🔥 FORCE VIDEO LOAD
                page.mouse.move(300, 400)
                page.mouse.wheel(0, 300)
                page.wait_for_timeout(2000)

                try:
                    page.click("video", timeout=3000)
                except:
                    pass

                page.wait_for_timeout(3000)

                # ✅ 1. PAGE SOURCE (PRIMARY)
                src = extract_from_page_source(page)
                if src:
                    found_url = src
                    break

                # ✅ 2. NETWORK FALLBACK
                if collected_m3u8:
                    found_url = pick_best_m3u8(collected_m3u8)
                    break

            except:
                continue

        browser.close()

        if not found_url:
            print("No video found in first 4 visible pins")
            sys.exit(1)

        print("Found video:", found_url)

        create_button_png()

        os.system(
            f'ffmpeg -y '
            f'-i "{found_url}" '
            f'-i "shop_now_btn.png" '
            f'-f lavfi -i anullsrc=r=44100:cl=stereo '
            f'-t 15 '
            f'-filter_complex '
            f'"[0:v]scale=720:1280[bg];'
            f'[bg][1:v]overlay=(W-w)/2:H-220" '
            f'-r 30 '
            f'-pix_fmt yuv420p '
            f'-c:v libx264 '
            f'-preset veryfast '
            f'-c:a aac '
            f'-b:a 128k '
            f'-shortest '
            f'output.mp4'
        )

        print("Saved as output.mp4")


if __name__ == "__main__":
    run()
