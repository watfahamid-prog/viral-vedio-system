import json
import math
import os
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
    words, lines, line = text.split(), [], ""
    for word in words:
        test = f"{line} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            line = test
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)
    return lines

def create_video(opportunity, script_data):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    work = os.path.join(OUTPUT_DIR, "frames")
    os.makedirs(work, exist_ok=True)
    scenes = script_data.get("scenes") or [script_data.get("hook", opportunity["hook"])]
    frames = max(1, int(VIDEO_SECONDS * FPS))

    for i in range(frames):
        t = i / FPS
        scene_index = min(len(scenes) - 1, int(t / VIDEO_SECONDS * len(scenes)))
        progress = (t / VIDEO_SECONDS) % 1
        img = Image.new("RGB", (WIDTH, HEIGHT), (12, 12, 18))
        draw = ImageDraw.Draw(img)
        for y in range(0, HEIGHT, 40):
            offset = int(40 * math.sin(t * 1.5 + y / 180))
            draw.rectangle((0, y, WIDTH, y + 40), fill=(18 + offset // 8, 20, 35))

        title_font, body_font, small_font = _font(76), _font(54), _font(38)
        draw.text((70, 110), "TRENDING NOW", font=small_font, fill="white")
        y = 300
        for line in _wrap(draw, script_data.get("title", "Trending now"), title_font, WIDTH - 140)[:3]:
            draw.text((70, y), line, font=title_font, fill="white")
            y += 95

        y = 900
        for line in _wrap(draw, scenes[scene_index], body_font, WIDTH - 140)[:5]:
            draw.text((70, y), line, font=body_font, fill="white")
            y += 68

        draw.text((70, 1760), f"{scene_index + 1}/{len(scenes)}", font=small_font, fill="white")
        draw.rectangle((70, 1840, 70 + int((WIDTH - 140) * progress), 1855), fill="white")
        img.save(os.path.join(work, f"frame_{i:05d}.png"))

    output = os.path.join(OUTPUT_DIR, "viral_short.mp4")
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i",
                    os.path.join(work, "frame_%05d.png"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", output],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    manifest = {"trend": opportunity["trend"], "hook": opportunity["hook"],
                "format": opportunity["format"], "duration_seconds": VIDEO_SECONDS,
                "original_content": True, "script": script_data, "video_file": output}
    with open(os.path.join(OUTPUT_DIR, "latest_video.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return output


def write_manifest(opportunity, script_data, video_path):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    manifest_path = os.path.join(
        OUTPUT_DIR,
        f"{os.path.splitext(os.path.basename(video_path))[0]}.json"
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
