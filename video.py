import json
import math
import os
import re
import subprocess
from PIL import Image, ImageDraw, ImageFont
from config import OUTPUT_DIR, VIDEO_SECONDS

WIDTH, HEIGHT, FPS = 1080, 1920, 15


def _font(size):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap(draw, text, font, max_width):
    words, lines, line = str(text).split(), [], ""
    for word in words:
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
    title_font, body_font, small_font = _font(76), _font(52), _font(38)

    for i in range(frames):
        t = i / FPS
        scene_index = min(len(scenes) - 1, int(t / VIDEO_SECONDS * len(scenes)))
        progress = min(1.0, t / VIDEO_SECONDS)
        img = Image.new("RGB", (WIDTH, HEIGHT), (9, 10, 20))
        draw = ImageDraw.Draw(img)

        # Animated layered background for a more dynamic short.
        pulse = int(18 * (0.5 + 0.5 * math.sin(t * 3.0)))
        for y in range(0, HEIGHT, 48):
            wave = int(18 * math.sin(t * 1.8 + y / 150))
            draw.rectangle((0, y, WIDTH, y + 48), fill=(14 + pulse // 3, 18 + wave // 4, 34 + pulse))
        for x in range(-200, WIDTH + 200, 220):
            drift = int(100 * math.sin(t * 0.7 + x / 250))
            draw.ellipse((x + drift, 450, x + drift + 320, 770), fill=(20, 28, 55))

        # Strong top label and hook/title hierarchy.
        draw.rounded_rectangle((60, 80, 430, 155), radius=28, fill=(255, 255, 255))
        draw.text((88, 96), "TRENDING NOW", font=small_font, fill=(8, 10, 18))

        y = 260
        title = script_data.get("title") or opportunity.get("trend", "Trending now")
        for line in _wrap(draw, title, title_font, WIDTH - 140)[:3]:
            draw.text((70, y), line, font=title_font, fill="white")
            y += 94

        # Scene card keeps text readable on a phone screen.
        card_top, card_bottom = 900, 1515
        draw.rounded_rectangle((55, card_top, WIDTH - 55, card_bottom), radius=42, fill=(8, 10, 18))
        scene_text = scenes[scene_index]
        y = card_top + 70
        for line in _wrap(draw, scene_text, body_font, WIDTH - 180)[:6]:
            draw.text((90, y), line, font=body_font, fill="white")
            y += 72

        # Scene indicator + progress bar.
        draw.text((70, 1650), f"PART {scene_index + 1}/{len(scenes)}", font=small_font, fill="white")
        draw.text((WIDTH - 360, 1650), "WATCH TO THE END", font=small_font, fill="white")
        draw.rounded_rectangle((70, 1760, WIDTH - 70, 1785), radius=12, fill=(55, 60, 80))
        draw.rounded_rectangle((70, 1760, 70 + int((WIDTH - 140) * progress), 1785), radius=12, fill="white")
        draw.text((70, 1830), "Follow for more", font=small_font, fill="white")

        img.save(os.path.join(work, f"frame_{i:05d}.png"))

    output = os.path.join(OUTPUT_DIR, f"viral_short_{run_id}.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-framerate", str(FPS), "-i",
        os.path.join(work, "frame_%05d.png"), "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", output,
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    manifest = {
        "trend": opportunity["trend"],
        "hook": opportunity["hook"],
        "format": opportunity["format"],
        "duration_seconds": VIDEO_SECONDS,
        "original_content": True,
        "script": script_data,
        "video_file": output,
    }
    with open(os.path.join(OUTPUT_DIR, f"latest_video_{run_id}.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return output


def write_manifest(opportunity, script_data, video_path):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    manifest_path = os.path.join(
        OUTPUT_DIR,
        f"{os.path.splitext(os.path.basename(video_path))[0]}.json",
    )
    manifest = {
        "trend": opportunity["trend"],
        "hook": opportunity["hook"],
        "format": opportunity["format"],
        "duration_seconds": VIDEO_SECONDS,
        "original_content": True,
        "script": script_data,
        "video_file": video_path,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest_path
