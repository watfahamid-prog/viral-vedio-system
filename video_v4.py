import json
import html
import math
import os
import re
import subprocess
import requests
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import OUTPUT_DIR, VIDEO_SECONDS, VIDEO_MIN_SECONDS, VIDEO_MAX_SECONDS

WIDTH, HEIGHT, FPS = 1080, 1920, 24

# Deliberately varied art direction: no single "blue template" for every video.
PALETTES = [
    ((11, 12, 17), (255, 255, 255), (255, 77, 92), (255, 184, 77)),
    ((18, 12, 30), (255, 250, 255), (255, 73, 177), (132, 92, 255)),
    ((8, 23, 24), (245, 255, 251), (38, 214, 169), (255, 193, 72)),
    ((15, 18, 34), (247, 249, 255), (86, 145, 255), (255, 199, 80)),
    ((27, 20, 13), (255, 249, 236), (245, 139, 54), (255, 214, 92)),
    ((13, 14, 15), (246, 246, 246), (224, 224, 224), (255, 75, 65)),
]

def _font(size):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def _regular(size):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return _font(size)

def _wrap(draw, text, fnt, width):
    words = str(text).split()
    lines, line = [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=fnt)[2] <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines

def _phrase(text, max_words=10):
    # Source feeds can contain HTML entities/tags; never let those leak into the video.
    cleaned = html.unescape(re.sub(r"<[^>]+>", " ", str(text)))
    cleaned = cleaned.replace("\\n", " ").replace("&nbsp;", " ")
    words = re.findall(r"[A-Za-zÅÄÖåäö0-9’'\-]+", cleaned)
    value = " ".join(words[:max_words]).strip()
    return value or "Here is what is happening"

def _slug(text):
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(text)).strip("-").lower()[:45] or "trend"

def _speech(script):
    text = html.unescape(str(script.get("script", "")).strip())
    if not text:
        text = " ".join(map(str, script.get("scenes", [])))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.replace("&nbsp;", " ").split())

def duration_for(script, opportunity):
    words = len(_speech(script).split())
    estimated = round(words / 2.65) if words else VIDEO_SECONDS
    fmt = str(opportunity.get("format", "")).lower()
    if "story" in fmt:
        estimated += 2
    if "quick" in fmt:
        estimated -= 2
    return max(VIDEO_MIN_SECONDS, min(VIDEO_MAX_SECONDS, estimated))

def _draw_gradient(img, top, bottom):
    px = img.load()
    for y in range(HEIGHT):
        mix = y / max(1, HEIGHT - 1)
        row = tuple(int(top[i] * (1 - mix) + bottom[i] * mix) for i in range(3))
        for x in range(WIDTH):
            px[x, y] = row

def _add_atmosphere(img, accent, hot, seed):
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i in range(8):
        x = int((seed * 137 + i * 173) % (WIDTH + 500) - 250)
        y = int((seed * 83 + i * 241) % (HEIGHT + 500) - 250)
        r = 110 + ((seed + i * 41) % 230)
        color = accent if i % 2 == 0 else hot
        d.ellipse((x-r, y-r, x+r, y+r), fill=(*color, 42))
    layer = layer.filter(ImageFilter.GaussianBlur(85))
    img.alpha_composite(layer)

def _safe_download(url, path):
    # Wikimedia and news CDNs can briefly return 429s on GitHub runners.
    # Retry politely and use a real browser-like identity before falling back.
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36 ViralVideoBot/7.0",
        "Referer": "https://commons.wikimedia.org/",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    for attempt in range(4):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "")
                try:
                    wait = min(6.0, max(1.5, float(retry_after)))
                except Exception:
                    wait = 2.0 + attempt
                time.sleep(wait)
                continue
            response.raise_for_status()
            data = response.content
            if len(data) < 12000:
                return False
            Path(path).write_bytes(data)
            with Image.open(path) as im:
                im.verify()
            return True
        except Exception as error:
            if attempt == 3:
                print(f"Visual asset download skipped: {error}")
            else:
                time.sleep(1.5 * (attempt + 1))
    Path(path).unlink(missing_ok=True)
    return False

def _fetch_visual_assets(opportunity, work):
    """Fetch topic-relevant imagery only; reject generic logos and unrelated search hits."""
    assets, credits = [], []
    trend = html.unescape(re.sub(r"^(källor|sources)[:\\s]+", "", str(opportunity.get("trend", "")), flags=re.I)).strip()
    query = " ".join(trend.split()[:10])

    # Search Wikimedia first. Image title/description must share a meaningful topic token.
    if query:
        try:
            api = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query", "generator": "search", "gsrsearch": query,
                    "gsrnamespace": 6, "gsrlimit": 10, "prop": "imageinfo",
                    "iiprop": "url|extmetadata", "iiurlwidth": 1080, "format": "json"
                },
                headers={"User-Agent": "ViralVideoBot/5.0"}, timeout=12
            )
            if api.ok:
                aliases = {
                    "ambulans": "ambulance", "ambulanss": "ambulance",
                    "fotboll": "football", "soccer": "football",
                    "trump": "trump", "iran": "iran", "hipp": "hipp"
                }
                terms = []
                for word in re.findall(r"[A-Za-zÅÄÖåäö0-9][A-Za-zÅÄÖåäö0-9'’\-]+", query.lower()):
                    if len(word) >= 4 and word not in {"this", "that", "with", "here", "sources", "källor"}:
                        terms.append(aliases.get(word, word))
                repeated_phrase = bool(re.search(r"\\b(\\w+)\\s+\\1\\b", query.lower()))
                terms = list(dict.fromkeys(terms))

                pages = (api.json().get("query", {}).get("pages", {}) or {}).values()
                scored = []
                for page_data in pages:
                    info = (page_data.get("imageinfo") or [{}])[0]
                    meta = info.get("extmetadata") or {}
                    title_text = str(page_data.get("title", ""))
                    desc_text = " ".join(
                        str(meta.get(k, {}).get("value", ""))
                        for k in ("ObjectName", "ImageDescription", "Categories")
                    )
                    haystack = html.unescape((title_text + " " + desc_text)).lower()
                    score = sum(1 for term in terms if term in haystack)
                    exact_phrase = query.lower() in haystack
                    if exact_phrase:
                        score += 5
                    # Repeated phrases such as "hipp hipp" must match the phrase itself;
                    # a random file containing only one "hipp" token is not relevant.
                    if repeated_phrase and not exact_phrase:
                        continue
                    # Multi-term topics need more than one weak token match.
                    required = 1 if len(terms) <= 1 else min(2, len(terms))
                    if score < required:
                        continue
                    url = info.get("thumburl") or info.get("url")
                    if not url:
                        continue
                    scored.append((score, page_data.get("pageid", 0), url, title_text))

                scored.sort(key=lambda x: (-x[0], x[1]))
                for n, (score, _, url, title_text) in enumerate(scored[:3]):
                    p = work / f"commons_{n:02d}.jpg"
                    if _safe_download(url, p):
                        try:
                            with Image.open(p) as im:
                                if min(im.size) < 420:
                                    p.unlink(missing_ok=True)
                                    continue
                        except Exception:
                            p.unlink(missing_ok=True)
                            continue
                        assets.append(str(p))
                        credits.append(f"Wikimedia Commons: {title_text[:100]}")
                        time.sleep(1.2)
        except Exception as error:
            print(f"Wikimedia visual search unavailable: {error}")

    # Only use a source OG image when it is large enough to be useful. A 300x300
    # generic site icon is worse than a clean generated editorial fallback.
    source_url = str(opportunity.get("source_url", "")).strip()
    if source_url and not assets:
        try:
            page = requests.get(source_url, headers={"User-Agent": "Mozilla/5.0 ViralVideoBot/5.0"}, timeout=12)
            if page.ok:
                match = re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)', page.text, re.I)
                if not match:
                    match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']', page.text, re.I)
                if match:
                    p = work / "source_og.jpg"
                    if _safe_download(match.group(1), p):
                        with Image.open(p) as im:
                            if min(im.size) >= 700:
                                assets.append(str(p))
                                credits.append("source image")
                            else:
                                p.unlink(missing_ok=True)
        except Exception as error:
            print(f"Source preview image unavailable: {error}")

    return assets[:6], credits[:6]

def _photo_frame(path, image_path, title, hook, scene, category, index, total, palette, style):
    """Editorial photo frame with strong hierarchy, varied composition and clean typography."""
    bg, ink, accent, hot = palette
    with Image.open(image_path).convert("RGB") as src:
        sw, sh = src.size
        ratio = WIDTH / HEIGHT
        # Use a deterministic but visibly different crop per scene.
        if sw / max(1, sh) > ratio:
            crop_w = max(1, int(sh * ratio))
            bias = ((index * 0.31) + (style * 0.13)) % 1.0
            left = max(0, min(sw - crop_w, int((sw - crop_w) * bias)))
            src = src.crop((left, 0, left + crop_w, sh))
        else:
            crop_h = max(1, int(sw / ratio))
            bias = ((index * 0.27) + (style * 0.17)) % 1.0
            top = max(0, min(sh - crop_h, int((sh - crop_h) * bias)))
            src = src.crop((0, top, sw, top + crop_h))
        photo = src.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS).convert("RGBA")

    mode = (index + style * 2) % 10
    canvas = photo.copy()

    # Every few shots gets a different editorial treatment instead of a repeated card.
    if mode == 0:
        # Full-bleed hero.
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle((0, 0, WIDTH, 680), fill=(*bg, 150))
        od.rectangle((0, 1460, WIDTH, HEIGHT), fill=(*bg, 125))
        canvas.alpha_composite(overlay)
    elif mode == 1:
        # Blurred depth + sharp portrait crop.
        backdrop = photo.filter(ImageFilter.GaussianBlur(24))
        tint = Image.new("RGBA", (WIDTH, HEIGHT), (*bg, 90))
        backdrop.alpha_composite(tint)
        canvas = backdrop
        card_w, card_h = 880, 1220
        x0, y0 = 100, 250
        card = photo.resize((card_w, card_h), Image.Resampling.LANCZOS)
        shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((x0+14, y0+22, x0+card_w+14, y0+card_h+22), radius=42, fill=(0,0,0,145))
        canvas.alpha_composite(shadow)
        mask = Image.new("L", (card_w, card_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,card_w,card_h), radius=42, fill=255)
        canvas.paste(card, (x0, y0), mask)
    elif mode == 2:
        # Large offset crop with a clean side panel.
        canvas = photo.filter(ImageFilter.GaussianBlur(2))
        d = ImageDraw.Draw(canvas)
        d.rectangle((0, 0, 355, HEIGHT), fill=(*bg, 205))
        d.rectangle((35, 300, 390, 1610), outline=(*accent, 220), width=3)
    elif mode == 3:
        # Monochrome editorial shot with a color accent.
        gray = photo.convert("L").convert("RGBA")
        colorized = Image.new("RGBA", (WIDTH, HEIGHT), (*ink, 255))
        colorized.alpha_composite(gray)
        canvas = colorized
        tint = Image.new("RGBA", (WIDTH, HEIGHT), (*bg, 70))
        canvas.alpha_composite(tint)
    elif mode == 6:
        # Magazine split: image dominates, headline sits in a narrow editorial rail.
        canvas = photo
        d = ImageDraw.Draw(canvas)
        d.rectangle((0, 0, 1080, 250), fill=(*bg, 215))
        d.rectangle((0, 0, 18, HEIGHT), fill=(*hot, 255))
        d.rectangle((900, 0, 1080, HEIGHT), fill=(*bg, 185))
    elif mode == 7:
        # Breaking-news treatment: giant number + compact headline, intentionally different from cards.
        canvas = photo.filter(ImageFilter.GaussianBlur(1))
        d = ImageDraw.Draw(canvas)
        d.rectangle((0, 0, WIDTH, 300), fill=(*bg, 220))
        d.rectangle((0, 0, WIDTH, 18), fill=(*hot, 255))
        d.text((70, 85), "JUST IN", font=_font(34), fill=(*hot, 255))
        d.text((770, 55), f"{index+1:02d}", font=_font(145), fill=(*ink, 245))
    elif mode == 8:
        # Picture-in-picture editorial layout with a strong negative-space zone.
        base = photo.filter(ImageFilter.GaussianBlur(12))
        base.alpha_composite(Image.new("RGBA", (WIDTH, HEIGHT), (*bg, 95)))
        canvas = base
        crop = photo.crop((120, 180, 960, 1420)).resize((820, 1210), Image.Resampling.LANCZOS)
        mask = Image.new("L", crop.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, crop.width, crop.height), radius=48, fill=255)
        canvas.paste(crop, (130, 250), mask)
    elif mode == 9:
        # Minimal documentary treatment: no card, only a bold lower-third and accent rule.
        canvas = photo
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle((0, 1280, WIDTH, HEIGHT), fill=(*bg, 205))
        od.rectangle((68, 1270, 1012, 1280), fill=(*hot, 255))
        canvas.alpha_composite(overlay)
    elif mode == 4:
        # Two-frame collage: same source, two different crops, no giant opaque UI.
        base = photo.filter(ImageFilter.GaussianBlur(18))
        base.alpha_composite(Image.new("RGBA", (WIDTH, HEIGHT), (*bg, 90)))
        canvas = base
        left = photo.crop((0, 0, WIDTH, HEIGHT)).resize((610, 1220), Image.Resampling.LANCZOS)
        right = photo.crop((260, 280, 900, 1500)).resize((400, 1220), Image.Resampling.LANCZOS)
        canvas.paste(left, (45, 330))
        canvas.paste(right, (635, 330))
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((45, 330, 655, 1550), radius=34, outline=(*ink, 180), width=3)
        d.rounded_rectangle((635, 330, 1035, 1550), radius=34, outline=(*accent, 220), width=3)
    else:
        # Clean lower-third documentary frame.
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
        od = ImageDraw.Draw(overlay)
        for y in range(1050, HEIGHT):
            a = int(15 + 170 * ((y-1050) / max(1, HEIGHT-1050)))
            od.line((0,y,WIDTH,y), fill=(*bg,a))
        canvas.alpha_composite(overlay)

    d = ImageDraw.Draw(canvas)
    safe = 68
    labels = ["HOOK", "CONTEXT", "DETAIL", "REACTION", "CHANGE", "PAYOFF", "ANGLE", "JUST IN", "FOCUS", "TAKEAWAY"]
    label = labels[min(mode, len(labels)-1)]
    headline = _phrase(hook if index == 0 else scene, 8 if index else 9)
    title_clean = _phrase(title, 7)

    # Compact, high-contrast top hierarchy.
    d.text((safe, 70), label, font=_font(25), fill=(*hot, 255))
    d.text((WIDTH-165, 70), f"{index+1:02d}", font=_font(25), fill=(*ink, 230))
    if index == 0:
        y = 135
        for line in _wrap(d, headline, _font(70), 900)[:3]:
            d.text((safe, y), line, font=_font(70), fill=(*ink, 255),
                   stroke_width=2, stroke_fill=(*bg, 180))
            y += 78
    elif mode in (2, 3):
        # Text on the editorial panel.
        y = 420 if mode == 2 else 1120
        max_w = 275 if mode == 2 else 900
        fsz = 42 if mode == 2 else 60
        for line in _wrap(d, headline, _font(fsz), max_w)[:5]:
            d.text((safe if mode == 2 else 70, y), line, font=_font(fsz),
                   fill=(*ink, 255), stroke_width=1, stroke_fill=(*bg, 170))
            y += fsz + 10
    elif mode == 6:
        # Magazine rail.
        y = 360
        for line in _wrap(d, headline, _font(55), 760)[:4]:
            d.text((safe, y), line, font=_font(55), fill=(*ink, 255))
            y += 64
    elif mode == 7:
        # Breaking-news lower-third.
        box = (55, 1350, 1025, 1785)
        d.rounded_rectangle(box, radius=36, fill=(*bg, 220), outline=(*hot, 230), width=3)
        y = 1410
        for line in _wrap(d, headline, _font(54), 900)[:4]:
            d.text((85, y), line, font=_font(54), fill=(*ink, 255))
            y += 62
    elif mode == 8:
        # Picture-in-picture headline under the image.
        d.rounded_rectangle((70, 1510, 1010, 1800), radius=32, fill=(*bg, 220))
        for j, line in enumerate(_wrap(d, headline, _font(48), 850)[:4]):
            d.text((105, 1545+j*56), line, font=_font(48), fill=(*ink, 255))
    elif mode == 9:
        # Documentary lower third.
        for j, line in enumerate(_wrap(d, headline, _font(56), 860)[:4]):
            d.text((70, 1340+j*64), line, font=_font(56), fill=(*ink, 255))
    else:
        # One restrained story card, not a second duplicate headline.
        box = (safe, 1450, WIDTH-safe, 1770)
        d.rounded_rectangle(box, radius=30, fill=(*bg, 165), outline=(*accent, 150), width=2)
        lines = _wrap(d, headline, _font(52), 860)[:4]
        for j, line in enumerate(lines):
            d.text((safe+26, 1490+j*61), line, font=_font(52), fill=(*ink, 255))
        d.text((safe+26, 1735), title_clean.upper(), font=_font(21), fill=(*ink, 190))

    # Small scene marker; avoid the previous oversized repeated UI.
    d.text((safe, 1848), "ORIGINAL EDIT", font=_font(17), fill=(*ink, 175))
    d.rounded_rectangle((WIDTH-265, 1838, WIDTH-68, 1850), radius=6, fill=(*ink, 80))
    d.rounded_rectangle((WIDTH-265, 1838, WIDTH-265 + int(197*((index+1)/max(1,total))), 1850),
                        radius=6, fill=(*hot, 230))
    canvas.convert("RGB").save(path, quality=95, optimize=True)

def _draw_category_icon(d, category, cx, cy, size, accent, hot):
    cat = str(category).lower()
    w = max(8, size // 18)
    if cat == "sports":
        d.ellipse((cx-size, cy-size, cx+size, cy+size), outline=accent, width=w)
        d.arc((cx-size//2, cy-size, cx+size//2, cy+size), 20, 155, fill=hot, width=w)
        d.arc((cx-size, cy-size//2, cx+size, cy+size//2), 200, 335, fill=hot, width=w)
    elif cat == "technology":
        d.rounded_rectangle((cx-size, cy-size, cx+size, cy+size), radius=size//5, outline=accent, width=w)
        for off in (-size//2, 0, size//2):
            d.line((cx-size-35, cy+off, cx-size, cy+off), fill=hot, width=w)
            d.line((cx+size, cy+off, cx+size+35, cy+off), fill=hot, width=w)
        d.ellipse((cx-size//3, cy-size//3, cx+size//3, cy+size//3), fill=hot)
    elif cat == "entertainment":
        pts = []
        for i in range(10):
            a = -math.pi/2 + i*math.pi/5
            r = size if i % 2 == 0 else size//2
            pts.append((cx + math.cos(a)*r, cy + math.sin(a)*r))
        d.polygon(pts, fill=accent)
        d.ellipse((cx-size//5, cy-size//5, cx+size//5, cy+size//5), fill=hot)
    else:
        for r in (size, int(size*.62), int(size*.28)):
            d.ellipse((cx-r, cy-r, cx+r, cy+r), outline=accent, width=w)
        d.ellipse((cx-18, cy-18, cx+18, cy+18), fill=hot)

def _topic_tokens(text, limit=5):
    words = re.findall(r"[A-Za-zÅÄÖåäö0-9][A-Za-zÅÄÖåäö0-9'’\-]+", str(text))
    stop = {"here","this","that","with","behind","what","why","the","and","from","into","about","simple","actual","change"}
    out = []
    for word in words:
        low = word.lower()
        if len(low) >= 3 and low not in stop and low not in out:
            out.append(low)
    return out[:limit]


def _draw_subject_visual(d, category, scene_index, trend, accent, hot, ink, bg):
    """Create a large subject-focused illustration so scenes are not text-only cards."""
    cx, cy = 540, 820
    cat = str(category).lower()
    tokens = _topic_tokens(trend)
    # Solid panels avoid the old transparent-RGBA-to-RGB white-box bug.
    panel = tuple(int(bg[i] * 0.72 + ink[i] * 0.28) for i in range(3))
    panel2 = tuple(int(bg[i] * 0.45 + accent[i] * 0.55) for i in range(3))
    d.rounded_rectangle((70, 520, 1010, 1370), radius=58, fill=panel, outline=(*accent, 210), width=4)

    if cat == "sports":
        # Track lanes + runner silhouette + stadium lights.
        for off in (-260, -130, 0, 130, 260):
            d.line((120, 1170+off//3, 960, 960+off//3), fill=(*accent, 170), width=7)
        d.ellipse((455, 675, 525, 745), fill=(*ink, 255))
        d.line((490, 745, 450, 900), fill=(*ink, 255), width=28)
        d.line((460, 800, 370, 850), fill=(*ink, 255), width=22)
        d.line((462, 805, 570, 760), fill=(*ink, 255), width=22)
        d.line((450, 900, 345, 1030), fill=(*ink, 255), width=24)
        d.line((450, 900, 585, 1010), fill=(*ink, 255), width=24)
        for x in (150, 880):
            d.polygon([(x,600),(x-55,850),(x+55,850)], fill=(*hot, 45))
            d.ellipse((x-16,580,x+16,612), fill=(*hot,255))
    elif cat == "technology":
        # Device + circuit/network visualization.
        d.rounded_rectangle((300, 625, 780, 1080), radius=45, fill=panel2, outline=(*ink, 230), width=8)
        d.rounded_rectangle((335, 660, 745, 980), radius=25, fill=(*bg, 255), outline=(*accent, 180), width=4)
        d.ellipse((505, 1005, 575, 1075), fill=(*accent,255))
        nodes=[(180,720),(900,700),(170,1120),(910,1120),(250,900),(830,930)]
        for x,y in nodes:
            d.line((x,y,540,820), fill=(*accent,150), width=5)
            d.ellipse((x-22,y-22,x+22,y+22), fill=(*hot,255))
    elif cat == "politics":
        # Neutral civic/document visual, without depicting a real politician.
        d.polygon([(290,1030),(790,1030),(740,800),(340,800)], fill=panel2)
        d.rectangle((325,1030,755,1100), fill=(*ink,230))
        for x in (390,470,550,630,710):
            d.rectangle((x,860,x+28,1030), fill=(*ink,210))
        d.polygon([(260,800),(540,650),(820,800)], fill=(*accent,220))
        d.rectangle((415,570,665,680), fill=(*ink,245))
        d.line((455,620,625,620), fill=(*hot,255), width=8)
        d.text((95, 1180), "DOCUMENTED UPDATE", font=_font(30), fill=(*hot,255))
    elif cat == "entertainment":
        # Cinema/stage visual with film strip and spotlight.
        d.rectangle((245,650,835,1010), fill=(*ink,230), outline=(*accent,220), width=6)
        d.polygon([(290,965),(790,965),(690,735),(390,735)], fill=panel2)
        d.ellipse((500,800,580,880), fill=(*hot,255))
        d.polygon([(540,875),(470,960),(610,960)], fill=(*hot,190))
        d.polygon([(120,560),(420,560),(470,650),(70,650)], fill=(*accent,100))
        d.polygon([(660,560),(960,560),(1010,650),(610,650)], fill=(*accent,100))
    else:
        # General visual changes by scene so the same abstract graphic is never repeated.
        variant = scene_index % 4
        if variant == 0:
            d.ellipse((320,610,760,1050), outline=(*accent,210), width=10)
            d.ellipse((400,690,680,970), outline=(*hot,180), width=7)
            d.ellipse((505,795,575,865), fill=(*hot,255))
            for angle in range(0,360,60):
                rad=math.radians(angle)
                x=int(540+350*math.cos(rad)); y=int(830+260*math.sin(rad))
                d.ellipse((x-18,y-18,x+18,y+18), fill=(*accent,255))
        elif variant == 1:
            d.line((150,1040,930,1040), fill=(*ink,180), width=8)
            points=[(190,980),(380,870),(560,930),(750,760),(900,820)]
            for a,b in zip(points,points[1:]):
                d.line((*a,*b), fill=(*accent,230), width=14)
            for n,(x,y) in enumerate(points):
                node_color = hot if n == len(points)-1 else accent
                d.ellipse((x-34,y-34,x+34,y+34), fill=(*node_color,255))
            d.text((150,590), "CHANGE →", font=_font(58), fill=(*ink,255))
        elif variant == 2:
            d.ellipse((300,650,760,1110), outline=(*accent,230), width=18)
            d.ellipse((420,770,640,990), outline=(*hot,220), width=10)
            d.line((760,1110,900,1240), fill=(*ink,255), width=35)
            d.ellipse((485,835,575,925), fill=(*accent,255))
            d.text((150,580), "ZOOM IN", font=_font(58), fill=(*hot,255))
        else:
            d.rounded_rectangle((180,650,900,1030), radius=45, fill=panel2, outline=(*accent,230), width=6)
            d.line((540,650,540,1030), fill=(*ink,180), width=5)
            d.text((250,735), "BEFORE", font=_font(34), fill=(*ink,255))
            d.text((635,735), "NOW", font=_font(34), fill=(*ink,255))
            d.ellipse((300,830,430,960), outline=(*hot,230), width=9)
            d.ellipse((650,820,800,970), fill=(*hot,210), outline=(*ink,220), width=6)
            d.polygon([(500,820),(580,820),(580,880),(650,880),(540,980),(430,880),(500,880)], fill=(*accent,230))
        d.line((160,1110,920,1110), fill=(*ink,180), width=6)
        d.ellipse((250,1085,285,1120), fill=(*hot,255))
        d.ellipse((530,1085,565,1120), fill=(*accent,255))
        d.ellipse((800,1085,835,1120), fill=(*ink,255))

    if tokens:
        chip_x = 95
        for token in tokens[:3]:
            w = min(260, 35 + len(token)*19)
            d.rounded_rectangle((chip_x, 1250, chip_x+w, 1315), radius=25, fill=(*bg,230), outline=(*hot,180), width=2)
            d.text((chip_x+18, 1268), token.upper(), font=_font(24), fill=(*ink,240))
            chip_x += w + 14


def _render_frame(path, title, hook, scene, category, index, total, palette, style):
    bg, ink, accent, hot = palette
    img = Image.new("RGBA", (WIDTH, HEIGHT), (*bg, 255))
    _add_atmosphere(img, accent, hot, index + style * 19)
    d = ImageDraw.Draw(img)

    # Thin cinematic frame and scene marker.
    d.rounded_rectangle((34, 34, WIDTH-34, HEIGHT-34), radius=46, outline=(*accent, 150), width=3)
    d.text((70, 72), "TREND / NOW", font=_font(27), fill=(*accent, 255))
    d.text((WIDTH-210, 72), f"{index+1:02d} / {total:02d}", font=_font(27), fill=(*ink, 255))

    # Every scene has a different composition.
    if index == 0:
        d.text((70, 160), "STOP SCROLLING.", font=_font(70), fill=(*hot, 255))
        y = 265
        for line in _wrap(d, _phrase(hook, 13), _font(88), 900)[:4]:
            d.text((70, y), line, font=_font(88), fill=(*ink, 255))
            y += 105
        _draw_category_icon(d, category, 825, 700, 125, accent, hot)
        _draw_subject_visual(d, category, index, title, accent, hot, ink, bg)
        d.text((70, 1400), "WHY THIS MATTERS", font=_font(28), fill=(*accent, 255))
        for j, line in enumerate(_wrap(d, _phrase(scene, 12), _font(52), 880)[:3]):
            d.text((70, 1455 + j*64), line, font=_font(52), fill=(*ink, 255))
    elif index == total - 1:
        d.text((70, 170), "THE PAYOFF", font=_font(32), fill=(*hot, 255))
        for r in (330, 250, 170):
            d.ellipse((540-r, 590-r, 540+r, 590+r), outline=(*accent, 210), width=7)
        d.ellipse((485, 535, 595, 645), fill=(*hot, 255))
        y = 880
        for line in _wrap(d, _phrase(scene, 13), _font(76), 920)[:4]:
            d.text((70, y), line, font=_font(76), fill=(*ink, 255))
            y += 94
        d.rounded_rectangle((70, 1390, 1010, 1545), radius=32, fill=(*hot, 235))
        d.text((105, 1430), "FOLLOW FOR THE NEXT UPDATE", font=_font(34), fill=(*bg, 255))
    else:
        layouts = index % 4
        if layouts == 0:
            d.text((70, 165), f"0{index+1}", font=_font(170), fill=(*accent, 55))
            d.text((80, 320), "THE DETAIL", font=_font(30), fill=(*hot, 255))
            y = 390
            for line in _wrap(d, _phrase(scene, 17), _font(78), 880)[:5]:
                d.text((80, y), line, font=_font(78), fill=(*ink, 255))
                y += 94
            d.rounded_rectangle((80, 950, 1000, 1430), radius=46, fill=tuple(int(bg[i] * 0.82 + ink[i] * 0.18) for i in range(3)), outline=(*accent, 170), width=3)
            d.text((120, 1010), "CONTEXT", font=_font(27), fill=(*accent, 255))
            for j, line in enumerate(_wrap(d, _phrase(hook, 18), _regular(43), 790)[:5]):
                d.text((120, 1080 + j*62), line, font=_regular(43), fill=(*ink, 255))
        elif layouts == 1:
            d.text((70, 165), "WHAT CHANGED?", font=_font(30), fill=(*hot, 255))
            _draw_subject_visual(d, category, index, title, accent, hot, ink, bg)
            d.rounded_rectangle((70, 1420, 1010, 1570), radius=30, fill=(*accent, 235))
            for j, line in enumerate(_wrap(d, _phrase(scene, 10), _font(46), 850)[:2]):
                d.text((100, 1440+j*55), line, font=_font(46), fill=(*bg, 255))
        elif layouts == 2:
            d.text((70, 165), "ZOOM IN", font=_font(30), fill=(*accent, 255))
            _draw_subject_visual(d, category, index, title, accent, hot, ink, bg)
            d.text((70, 1420), "THE QUICK VERSION", font=_font(29), fill=(*hot, 255))
            for j, line in enumerate(_wrap(d, _phrase(hook, 11), _regular(42), 880)[:3]):
                d.text((70, 1470+j*55), line, font=_regular(42), fill=(*ink, 255))
        else:
            d.text((70, 160), "BREAKDOWN", font=_font(30), fill=(*hot, 255))
            _draw_subject_visual(d, category, index, title, accent, hot, ink, bg)
            d.text((70, 1400), "WHAT TO NOTICE", font=_font(28), fill=(*accent, 255))
            for j, line in enumerate(_wrap(d, _phrase(scene, 11), _font(52), 880)[:3]):
                d.text((70, 1455 + j*64), line, font=_font(52), fill=(*ink, 255))

    # Minimal top progress indicator leaves a dedicated clean subtitle zone at the bottom.
    bar_y = 112
    d.rounded_rectangle((70, bar_y, 1010, bar_y+8), radius=4, fill=tuple(int(bg[i] * 0.55 + ink[i] * 0.45) for i in range(3)))
    progress = (index + 1) / total
    d.rounded_rectangle((70, bar_y, int(70 + 940*progress), bar_y+8), radius=4, fill=(*hot, 255))
    img.convert("RGB").save(path, quality=95, optimize=True)

def _make_audio(script, work, duration):
    voice = Path(work) / "voice.wav"
    text = _speech(script)
    # Prefer the free Gemini TTS engine when a Gemini key is configured.
    try:
        from gemini_tts import gemini_tts
        gemini_path = work / "voice_gemini.wav"
        generated = gemini_tts(text, str(gemini_path))
        if generated:
            converted = work / "voice_gemini_48k.wav"
            subprocess.run(["ffmpeg", "-y", "-i", generated, "-ar", "48000", "-ac", "1",
                            "-c:a", "pcm_s16le", str(converted)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Voice engine: Gemini free-tier TTS")
            return str(converted)
    except Exception as error:
        print(f"Gemini TTS unavailable, using local fallback: {error}")
    try:
        edge_voice = os.getenv("TTS_VOICE", "en-US-GuyNeural")
        edge = work / "voice.mp3"
        subprocess.run(
            ["edge-tts", "--voice", edge_voice, "--text", text, "--write-media", str(edge)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=35,
        )
        subprocess.run(["ffmpeg", "-y", "-i", str(edge), "-ar", "48000", "-ac", "1",
                        "-c:a", "pcm_s16le", str(voice)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(voice)
    except Exception:
        subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", "170", "-p", "50", "-a", "165", "-w", str(voice), text],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Add a quiet original rhythmic bed and normalize narration.
        music = Path(work) / "bed.wav"
        mixed = Path(work) / "audio.wav"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"sine=frequency=96:duration={duration}",
            "-filter:a", f"volume=0.012,lowpass=f=220,afade=t=in:st=0:d=0.8,afade=t=out:st={max(0,duration-0.8)}:d=0.8",
            "-c:a", "pcm_s16le", str(music)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([
            "ffmpeg", "-y", "-i", str(voice), "-i", str(music),
            "-filter_complex",
            "[0:a]atrim=0:%s,asetpts=N/SR/TB,volume=1.0[v];"
            "[1:a]atrim=0:%s,asetpts=N/SR/TB[m];"
            "[v][m]amix=inputs=2:duration=longest:dropout_transition=0,"
            "loudnorm=I=-14:TP=-1.5:LRA=8[a]" % (duration, duration),
            "-map", "[a]", "-t", str(duration), "-c:a", "pcm_s16le", str(mixed)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(mixed)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

def _make_captions(script, duration, work):
    """Short, readable captions designed for mobile viewing and safe-area compliance."""
    path = Path(work) / "captions.ass"
    scenes = [str(x).strip() for x in (script.get("scenes") or []) if str(x).strip()]
    if not scenes:
        scenes = [str(script.get("hook", ""))]
    weights = [max(1, len(s.split())) for s in scenes]
    total = sum(weights) or 1

    def stamp(value):
        cs = int(round((value - int(value)) * 100))
        return f"0:{int(value)//60:02d}:{int(value)%60:02d}.{cs:02d}"

    def esc(value):
        value = html.unescape(re.sub(r"<[^>]+>", " ", str(value)))
        value = value.replace("&nbsp;", " ")
        return str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")

    with path.open("w", encoding="utf-8") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n")
        f.write("[V4+ Styles]\n")
        f.write("Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n")
        f.write("Style: Viral,DejaVu Sans,42,&H00FFFFFF,&H00FFFFFF,&H00101010,&HAA101010,-1,0,0,0,100,100,0,0,3,2,1,2,80,80,180,1\n\n")
        f.write("[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
        cursor = 0.0
        for i, scene in enumerate(scenes):
            step = duration * weights[i] / total
            start, end = cursor, min(duration, cursor + step)
            cursor = end
            # Captions are deliberately shorter than the spoken sentence.
            words = re.findall(r"[A-Za-zÅÄÖåäö0-9’'\-]+", html.unescape(scene))
            if len(words) > 7:
                words = words[:7]
            caption = " ".join(words).strip()
            if not caption:
                continue
            if len(words) > 5:
                mid = (len(words)+1)//2
                caption = " ".join(words[:mid]) + "\\N" + " ".join(words[mid:])
            f.write(f"Dialogue: 0,{stamp(start)},{stamp(end)},Viral,,0,0,0,,{esc(caption)}\n")
    return str(path)

def _build_segment(keyframe, output, seconds, direction, first=False, last=False):
    """Add a visible camera move to every still instead of making a static slideshow."""
    frames=max(1,int(round(seconds*FPS)))
    zoom_step=0.00185 if direction>0 else 0.00155
    zoom=f"min(zoom+{zoom_step:.5f},1.16)"
    if direction>0:
        x="iw/2-(iw/zoom/2)+((iw-iw/zoom)*0.28)"
        y="ih/2-(ih/zoom/2)+((ih-ih/zoom)*0.18)"
    else:
        x="iw/2-(iw/zoom/2)-((iw-iw/zoom)*0.24)"
        y="ih/2-(ih/zoom/2)-((ih-ih/zoom)*0.14)"
    vf=(f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        "format=yuv420p,"
        + ("fade=t=in:st=0:d=0.12," if first else "")
        + (f"fade=t=out:st={max(0,seconds-0.12):.3f}:d=0.12" if last else ""))
    subprocess.run(["ffmpeg","-y","-loop","1","-i",keyframe,"-vf",vf,"-t",f"{seconds:.3f}",
                    "-an","-c:v","libx264","-preset","veryfast","-crf","18",
                    "-pix_fmt","yuv420p","-movflags","+faststart",output],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def _try_ai_hero(opportunity, script, work, duration):
    """Use one optional real generative-video hero shot when credentials exist."""
    try:
        from ai_video import generate_clip
        visual = (script.get("visual_scenes") or [])[0]
        prompt = (
            f"Vertical 9:16 original cinematic footage. {visual} "
            "No readable text, no logos, no watermark, no celebrity likeness, "
            "natural motion, realistic lighting, clean composition."
        )
        path = work / "ai_hero.mp4"
        return generate_clip(prompt, str(path), duration=min(5, max(3, duration)))
    except Exception as error:
        print(f"Optional AI hero unavailable; using native renderer: {error}")
        return None


def create_video(opportunity, script, index=1):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    slug = _slug(opportunity.get("trend", "trend"))
    run_id = f"{index:02d}-{slug}"
    work = Path(OUTPUT_DIR) / f"v4-{run_id}"
    work.mkdir(parents=True, exist_ok=True)

    duration = duration_for(script, opportunity)
    scenes = [str(x).strip() for x in (script.get("scenes") or []) if str(x).strip()]
    if not scenes:
        scenes = [str(script.get("hook") or opportunity.get("trend", "Current topic"))]
    # Faster visual rhythm: 8-10 scenes gives each idea room without becoming a slideshow.\n    target = max(8, min(10, math.ceil(duration / 2.35)))
    base = list(scenes)
    while len(scenes) < target:
        scenes.append(base[len(scenes) % len(base)])
    scenes = scenes[:target]

    title = str(script.get("title") or opportunity.get("trend", "Current topic"))
    hook = str(script.get("hook") or opportunity.get("hook", "Here is what is happening."))
    category = str(opportunity.get("category", "general"))
    palette = PALETTES[(index - 1) % len(PALETTES)]
    style = (index - 1) % 4
    scene_time = duration / len(scenes)

    assets, asset_credits = _fetch_visual_assets(opportunity, work)
    keys = []
    for i, scene in enumerate(scenes):
        key = work / f"key_{i:02d}.jpg"
        if assets:
            # Use different topic assets when available. If there is only one, the renderer
            # still creates six materially different editorial treatments.
            asset = assets[i % len(assets)]
            _photo_frame(str(key), asset, title, hook, scene, category, i, len(scenes), palette, style)
        else:
            _render_frame(str(key), title, hook, scene, category, i, len(scenes), palette, style)
        keys.append(str(key))

    segments = []
    ai_hero = _try_ai_hero(opportunity, script, work, scene_time)
    if ai_hero and Path(ai_hero).exists():
        hero = work / "hero_normalized.mp4"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", ai_hero,
                "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p",
                "-an", "-t", f"{min(scene_time, 5):.3f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                "-movflags", "+faststart", str(hero)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segments.append(str(hero))
        except Exception as error:
            print(f"AI hero normalization failed; continuing with native visuals: {error}")

    for i, key in enumerate(keys):
        seg = work / f"seg_{i:02d}.mp4"
        _build_segment(
            key, str(seg), scene_time,
            direction=1 if (i + style) % 2 == 0 else -1,
            first=(i == 0), last=(i == len(keys)-1)
        )
        segments.append(str(seg))

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{os.path.abspath(p)}'\n" for p in segments), encoding="utf-8")
    silent = work / "silent.mp4"
    out = Path(OUTPUT_DIR) / f"viral_short_v4_{run_id}.mp4"

    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", str(silent)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Video assembly failed: " + "\n".join((exc.stderr or "").splitlines()[-20:]))

    audio = _make_audio(script, work, duration)
    if not audio:
        raise RuntimeError("Narration engine unavailable; refusing to create a silent video.")

    captions = _make_captions(script, duration, work)
    final_tmp = work / "final.mp4"
    # Burn captions into the final video so the artifact is immediately usable.
    subtitle_filter = captions.replace("\\", "/").replace(":", "\\:")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(silent), "-i", audio,
        "-vf", f"ass='{subtitle_filter}'",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-t", str(duration), "-movflags", "+faststart", str(final_tmp)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    os.replace(final_tmp, out)
    manifest = {
        "trend": opportunity.get("trend"),
        "visual_assets": assets,
        "visual_asset_credits": asset_credits,
        "format": opportunity.get("format", "short_explainer"),
        "platform": opportunity.get("platform", "shorts"),
        "duration_seconds": duration,
        "scene_count": len(scenes),
        "audio": True,
        "captions": True,
        "original_content": True,
        "visual_engine": "viral_editorial_v4_10_scene_archetypes_topic_assets_kinetic_motion_optional_ai_hero",
        "art_direction": f"palette-{(index-1)%len(PALETTES)+1}/layout-set-{style+1}",
        "script": script,
        "video_file": str(out),
    }
    with open(out.with_suffix(".json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return str(out)

def write_manifest(opportunity, script_data, video_path):
    path = Path(OUTPUT_DIR) / (Path(video_path).stem + ".json")
    data = {
        "trend": opportunity.get("trend"),
        "hook": opportunity.get("hook"),
        "format": opportunity.get("format", "short_explainer"),
        "platform": opportunity.get("platform", "shorts"),
        "duration_seconds": duration_for(script_data, opportunity),
        "scene_count": len(script_data.get("scenes", [])),
        "audio": True,
        "captions": True,
        "original_content": True,
        "visual_engine": "kinetic_motion_v4_optional_ai_hero",
        "script": script_data,
        "video_file": video_path,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)