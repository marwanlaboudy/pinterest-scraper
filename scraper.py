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


def dismiss_modal(page):
    try:
        close = page.locator("[data-test-id='fullPageSignupModal'] [aria-label='Close']")
        if close.is_visible(timeout=3000):
            close.click()
            page.wait_for_timeout(1000)
            log("Closed signup modal")
    except:
        pass


def close_filters(page):
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        page.mouse.click(640, 300)
        page.wait_for_timeout(800)
        log("Closed filter panel")
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


def title_matches_product(page, product_title):
    try:
        h1 = page.locator("h1").first
        pin_title = h1.inner_text(timeout=5000).lower()
        log(f"Pin title: '{pin_title}'")

        # Only ignore grammar/filler words — all product words count
        stopwords = {
            "the", "and", "for", "with", "from", "this", "that", "your", "are",
            "its", "into", "have", "has", "was", "will", "can", "not", "but",
            "also", "more", "than", "then", "when", "what", "which", "who"
        }

        product_words = [
            w for w in re.sub(r'[^a-z0-9 ]', '', product_title.lower()).split()
            if len(w) > 2 and w not in stopwords
        ]

        log(f"Checking keywords: {product_words}")

        matches = sum(1 for w in product_words if w in pin_title)
        log(f"Matches: {matches}/{len(product_words)} — need > 3")

        return matches > 3

    except Exception as e:
        log(f"Title check failed: {e} — allowing pin through")
        return True

def get_best_stream_url(master_url):
    """Parse the master m3u8 and return the highest bandwidth variant URL."""
    try:
        log(f"Fetching master playlist: {master_url}")
        r = requests.get(master_url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        lines = r.text.splitlines()
        log(f"Master playlist:\n{r.text[:800]}")

        best_bw = -1
        best_url = None
        base = master_url.rsplit("/", 1)[0]

        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("#EXT-X-STREAM-INF"):
                bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                bw = int(bw_match.group(1)) if bw_match else 0
                res_match = re.search(r'RESOLUTION=(\d+x\d+)', line)
                res = res_match.group(1) if res_match else "?"
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if next_line and not next_line.startswith("#"):
                    url = next_line if next_line.startswith("http") else f"{base}/{next_line}"
                    log(f"  Stream: {res} bw={bw} -> {url}")
                    if bw > best_bw:
                        best_bw = bw
                        best_url = url
            i += 1

        if best_url:
            log(f"Best stream: bw={best_bw} -> {best_url}")
            return best_url
        else:
            log("No variants found, using master directly")
            return master_url

    except Exception as e:
        log(f"Failed to parse master m3u8: {e}")
        return master_url


def get_audio_url(master_url):
    """Extract audio stream URL from master playlist."""
    try:
        r = requests.get(master_url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        base = master_url.rsplit("/", 1)[0]
        for line in r.text.splitlines():
            if '#EXT-X-MEDIA' in line and 'TYPE=AUDIO' in line:
                uri_match = re.search(r'URI="([^"]+)"', line)
                if uri_match:
                    uri = uri_match.group(1)
                    audio_url = uri if uri.startswith("http") else f"{base}/{uri}"
                    log(f"Audio stream: {audio_url}")
                    return audio_url
    except Exception as e:
        log(f"Audio extraction failed: {e}")
    return None


def extract_m3u8_from_page(page):
    try:
        content = page.content()
        patterns = [
            r'(https://v(?:1|2)\.pinimg\.com/videos/[^"\'\\]+\.m3u8)',
            r'(https://[^"\'\\]*pinimg\.com[^"\'\\]*\.m3u8)',
        ]
        found = []
        for pattern in patterns:
            for m in re.findall(pattern, content):
                clean = m.encode().decode('unicode_escape') if '\\u' in m else m
                clean = clean.replace('\\/', '/')
                if not re.search(r'_\d+w|_audio|h265', clean):
                    found.append(clean)
                    log(f"Found master in HTML: {clean}")
        return list(dict.fromkeys(found))
    except Exception as e:
        log(f"HTML extraction failed: {e}")
        return []


def create_button_png(path="shop_now_btn.png"):
    W, H = 500, 110
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([0, 0, W-1, H-1], radius=55, fill=(255, 255, 255, 245))
    draw.rounded_rectangle([0, 0, W-1, H-1], radius=55, outline=(20, 20, 20, 255), width=4)

    try:
        font = ImageFont.truetype(FONT_PATH, size=48)
    except Exception as e:
        log(f"Font load failed: {e}, using fallback")
        font = ImageFont.load_default()

    text = "SHOP NOW"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (W - tw) // 2 - bbox[0]
    y = (H - th) // 2 - bbox[1]

    draw.text((x+2, y+2), text, fill=(100, 100, 100, 180), font=font)
    draw.text((x, y), text, fill=(20, 20, 20, 255), font=font)

    img.save(path)
    log(f"Created button: {W}x{H}px")


def run():
    with sync_playwright() as p:
        log("Launching browser...")
        log(f"Query: {query}")
        log(f"Product title: {product_title}")

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            java_script_enabled=True,
        )

        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = context.new_page()

        all_m3u8 = []

        def on_response(resp):
            try:
                url = resp.url
                if ".m3u8" in url and "pinimg.com" in url:
                    if not re.search(r'_\d+w|_audio|h265', url):
                        log(f"[NET] Master m3u8: {url}")
                        all_m3u8.append(url)
                    else:
                        log(f"[NET] Skipping variant: {url}")
            except:
                pass

        page.on("response", on_response)

        search_url = f"https://www.pinterest.com/search/videos/?q={query.replace(' ', '+')}"
        goto_with_retry(page, search_url)

        log("Waiting for initial load...")
        page.wait_for_timeout(WAIT)

        dismiss_modal(page)
        close_filters(page)

        pins = page.locator("div[data-test-id='pin']")
        pins.first.wait_for(timeout=20000)

        total = pins.count()
        log(f"Total pins found: {total}")

        pin_data = []
        for i in range(total):
            try:
                box = pins.nth(i).bounding_box()
                if not box:
                    continue
                x, y = box["x"], box["y"]
                log(f"Pin {i} X:{x:.0f} Y:{y:.0f}")
                href = pins.nth(i).locator("a").first.get_attribute("href", timeout=3000)
                if href:
                    pin_data.append({"i": i, "x": x, "y": y, "href": href})
            except Exception as e:
                log(f"Pin {i} failed: {e}")
                continue

        log(f"\nCollected {len(pin_data)} pins")
        pin_data.sort(key=lambda p: (round(p["y"] / 100) * 100, p["x"]))

        log("\nVisual order (first 8):")
        for p in pin_data[:8]:
            log(f"  Pin {p['i']} X:{p['x']:.0f} Y:{p['y']:.0f} href:{p['href']}")

        # Check more pins since some will be filtered by title
        top_hrefs = [p["href"] for p in pin_data[:10]]
        log(f"\nWill check up to {len(top_hrefs)} pins in visual order")

        found_master = None

        for i, href in enumerate(top_hrefs):
            log(f"\n--- PIN {i+1} ---")
            pin_url = f"https://www.pinterest.com{href}"
            log(f"Opening pin: {pin_url}")

            before_count = len(all_m3u8)

            try:
                if not goto_with_retry(page, pin_url):
                    continue

                page.wait_for_timeout(2000)

                # ✅ Check title match BEFORE waiting for video
                if not title_matches_product(page, product_title, threshold=0.3):
                    log("❌ Title mismatch — skipping pin")
                    continue

                log("✅ Title matches — checking for video...")
                page.mouse.move(300, 400)
                page.wait_for_timeout(3000)

                new_urls = all_m3u8[before_count:]
                log(f"Network captured {len(new_urls)} new master streams")

                html_urls = extract_m3u8_from_page(page)
                log(f"HTML extraction found {len(html_urls)} master streams")

                combined = list(dict.fromkeys(new_urls + html_urls))
                log(f"Combined unique masters: {len(combined)}")

                if combined:
                    found_master = combined[0]
                    log(f"Using master: {found_master}")
                    break

            except Exception as e:
                log(f"Error: {e}")
                continue

        browser.close()

        if not found_master:
            log("No video found in pins")
            sys.exit(1)

        best_video_url = get_best_stream_url(found_master)
        audio_url = get_audio_url(found_master)

        log(f"FINAL VIDEO STREAM: {best_video_url}")
        log(f"FINAL AUDIO STREAM: {audio_url}")

        create_button_png()
        log("Running ffmpeg...")

        if audio_url:
            cmd = (
                f'ffmpeg -y '
                f'-i "{best_video_url}" '
                f'-i "{audio_url}" '
                f'-i "shop_now_btn.png" '
                f'-filter_complex '
                f'"[0:v]scale=720:1280:force_original_aspect_ratio=decrease,'
                f'pad=720:1280:(ow-iw)/2:(oh-ih)/2[bg];'
                f'[bg][2:v]overlay=(W-w)/2:H-160[out]" '
                f'-map "[out]" -map 1:a '
                f'-c:v libx264 -preset fast -crf 18 '
                f'-c:a aac -b:a 128k -shortest output.mp4'
            )
        else:
            cmd = (
                f'ffmpeg -y '
                f'-i "{best_video_url}" '
                f'-i "shop_now_btn.png" '
                f'-f lavfi -i anullsrc=r=44100:cl=stereo '
                f'-filter_complex '
                f'"[0:v]scale=720:1280:force_original_aspect_ratio=decrease,'
                f'pad=720:1280:(ow-iw)/2:(oh-ih)/2[bg];'
                f'[bg][1:v]overlay=(W-w)/2:H-160[out]" '
                f'-map "[out]" -map 2:a '
                f'-c:v libx264 -preset fast -crf 18 '
                f'-c:a aac -b:a 128k -shortest output.mp4'
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
