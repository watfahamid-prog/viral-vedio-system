import json
import math
import os
import re
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFont
from config import OUTPUT_DIR, VIDEO_SECONDS

WIDTH, HEIGHT, FPS = 1080, 1920, 15

def _font(size):
    for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def _wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in str(text).split():
        test = f"{line} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines

def _slug(text):
    value = re.sub(r"[^a-zA-Z0-9]+", "-", str(text)).strip("-").lower()
    return value[:45] or "viral-short"

def create_video(opportunity, script_data, index=1):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    run_id = f"{index:02d}-{_slug(opportunity.get('trend', 'trend'))}"
    work = os.path.join(OUTPUT_DIR, f"frames-{run_id}")
    os.makedirs(work, exist_ok=True)

    scenes = script_data.get("scenes") or [script_data.get("hook", opportunity["hook"])]
    frames = max(1, int(VIDEO_SECONDS * FPS))
    title_font, body_font = _font(76), _font(50)
    category = str(opportunity.get("category", "general"))
    style = {"sports": "SPORTS PULSE", "technology": "TECH PULSE", "entertainment": "TREND ALERT", "general": "QUICK EXPLAINER"}.get(category, "QUICK EXPLAINER")
    small_font, tiny_font = _font(34), _font(28)

    for i in range(frames):
        t = i / FPS
        progress = min(1.0, t / VIDEO_SECONDS)
        scene_index = min(len(scenes) - 1, int(progress * len(scenes)))
        img = Image.new("RGB", (WIDTH, HEIGHT), (7, 9, 18))
        draw = ImageDraw.Draw(img)

        pulse = 0.5 + 0.5 * math.sin(t * 3.2)
        for y in range(0, HEIGHT, 40):
            wave = 0.5 + 0.5 * math.sin(t * 1.7 + y / 130)
            draw.rectangle((0, y, WIDTH, y + 40),
                           fill=(int(8+12*wave+7*pulse),
                                 int(10+15*wave+5*pulse),
                                 int(24+28*wave+16*pulse)))
        for n, x in enumerate(range(-250, WIDTH + 300, 260)):
            drift = int(130 * math.sin(t * 0.65 + n))
            size = 260 + int(35 * math.sin(t + n))
            draw.ellipse((x+drift, 360+n*70, x+drift+size, 360+n*70+size),
                         fill=(18+n%5, 25+n%7, 52+n%9))

        format_label = style + " • " + str(opportunity.get("format", "quick_explainer")).replace("_", " ").upper()
        badge_width = min(760, 80 + len(format_label) * 22)
        draw.rounded_rectangle((55, 70, badge_width, 150), radius=28, fill=(245,245,245))
        draw.text((83, 92), format_label, font=small_font, fill=(7,9,18))

        title = script_data.get("title") or opportunity.get("trend", "Trending now")
        y = 235 - min(25, int((1-min(progress*5,1))*25))
        for line in _wrap(draw, title, title_font, WIDTH-140)[:3]:
            draw.text((70, y), line, font=title_font, fill="white")
            y += 92

        hook = script_data.get("hook") or opportunity.get("hook", "")
        draw.rounded_rectangle((60, 555, WIDTH-60, 760), radius=34, fill=(245,245,245))
        draw.text((90, 585), "HOOK", font=tiny_font, fill=(30,30,35))
        y = 625
        hook_font = _font(42)
        for line in _wrap(draw, hook, hook_font, WIDTH-180)[:3]:
            draw.text((90, y), line, font=hook_font, fill=(10,12,20))
            y += 52

        shift = int(18 * math.sin(t * 2.2) + 8 * math.sin(t * 4.7))
        top = 875 + shift
        bottom = 1485 + shift
        card_x = int(55 + 10 * math.sin(t * 2.5))
        draw.rounded_rectangle((card_x, top, WIDTH-55, bottom), radius=42, fill=(6,8,16))
        draw.text((90, top+55), f"SCENE {scene_index+1}  •  {category.upper()}", font=tiny_font, fill="white")
        y = top + 125
        for line in _wrap(draw, scenes[scene_index], body_font, WIDTH-180)[:6]:
            draw.text((90, y), line, font=body_font, fill="white")
            y += 70

        total = max(1, len(scenes))
        start = WIDTH//2 - ((total-1)*22)
        for n in range(total):
            x = start + n*44
            r = 9 if n == scene_index else 7
            draw.ellipse((x-r,1575-r,x+r,1575+r), fill="white")

        draw.rounded_rectangle((65,1660,WIDTH-65,1688), radius=14, fill=(55,60,78))
        draw.rounded_rectangle((65,1660,65+int((WIDTH-130)*progress),1688),
                               radius=14, fill="white")
        draw.text((70,1735), f"{int(progress*100):02d}%", font=tiny_font, fill="white")
        draw.text((WIDTH-350,1735), "WATCH TO THE END", font=tiny_font, fill="white")
        draw.text((70,1815), "Follow for more quick trend breakdowns",
                  font=small_font, fill="white")
        img.save(os.path.join(work, f"frame_{i:05d}.png"))

    output = os.path.join(OUTPUT_DIR, f"viral_short_{run_id}.mp4")
    subprocess.run(["ffmpeg","-y","-framerate",str(FPS),"-i",
                    os.path.join(work,"frame_%05d.png"),"-c:v","libx264",
                    "-pix_fmt","yuv420p","-movflags","+faststart",output],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Keep artifacts small: PNG frames are only build intermediates.
    shutil.rmtree(work, ignore_errors=True)

    # Basic output gate: never report a video that was not actually created.
    if not os.path.exists(output) or os.path.getsize(output) < 50_000:
        raise RuntimeError(f"Video quality gate failed: missing or tiny output: {output}")

    manifest = {"trend":opportunity["trend"],"hook":opportunity["hook"],
                "format":opportunity["format"],"duration_seconds":VIDEO_SECONDS,
                "original_content":True,"script":script_data,"video_file":output}
    with open(os.path.join(OUTPUT_DIR,f"latest_video_{run_id}.json"),"w",encoding="utf-8") as f:
        json.dump(manifest,f,ensure_ascii=False,indent=2)
    return output

def write_manifest(opportunity, script_data, video_path):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{os.path.splitext(os.path.basename(video_path))[0]}.json")
    manifest = {"trend":opportunity["trend"],"hook":opportunity["hook"],
                "format":opportunity["format"],"duration_seconds":VIDEO_SECONDS,
                "original_content":True,"script":script_data,"video_file":video_path}
    with open(path,"w",encoding="utf-8") as f:
        json.dump(manifest,f,ensure_ascii=False,indent=2)
    return path
