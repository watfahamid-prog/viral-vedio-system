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
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]:
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


def _clean_speech(script_data):
    text = str(script_data.get("script", "")).strip()
    if not text:
        text = " ".join(str(x) for x in script_data.get("scenes", []))
    return re.sub(r"\s+", " ", text)


def _make_audio(script_data, output, duration):
    """Create free narration plus subtle generated background music."""
    speech = _clean_speech(script_data)
    if not speech:
        return None

    work = os.path.dirname(output)
    voice = os.path.join(work, "voice.wav")
    music = os.path.join(work, "music.wav")
    mixed = os.path.join(work, "audio.wav")

    voice_cmd = [
        "espeak-ng", "-v", "en-us", "-s", "180", "-p", "48",
        "-a", "155", "-w", voice, speech
    ]
    try:
        subprocess.run(voice_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "sine=frequency=110:duration="+str(duration),
            "-filter_complex",
            "[0:a]volume=0.045,afade=t=in:st=0:d=1,afade=t=out:st="+str(max(0, duration-1))+":d=1[m]",
            "-c:a", "pcm_s16le", music
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Keep narration clear and music quiet. The final mix is exactly video length.
        subprocess.run([
            "ffmpeg", "-y", "-i", voice, "-i", music,
            "-filter_complex",
            "[0:a]atrim=0:"+str(duration)+",asetpts=N/SR/TB,volume=1.0[v];"
            "[1:a]atrim=0:"+str(duration)+",asetpts=N/SR/TB[m];"
            "[v][m]amix=inputs=2:duration=longest:dropout_transition=0,"
            "loudnorm=I=-16:TP=-1.5:LRA=11[a]",
            "-map", "[a]", "-t", str(duration), "-c:a", "pcm_s16le", mixed
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return mixed
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def create_video(opportunity, script_data, index=1):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    run_id = f"{index:02d}-{_slug(opportunity.get('trend', 'trend'))}"
    work = os.path.join(OUTPUT_DIR, f"frames-{run_id}")
    os.makedirs(work, exist_ok=True)

    scenes = script_data.get("scenes") or [script_data.get("hook", opportunity["hook"])]
    frames = max(1, int(VIDEO_SECONDS * FPS))
    title_font, body_font = _font(76), _font(50)
    category = str(opportunity.get("category", "general"))
    format_name = str(opportunity.get("format", "short_explainer"))
    style = {
        "youtube_ranked_breakdown": "YOUTUBE RANKED",
        "tiktok_cantina_story": "TIKTOK STORY",
        "youtube_quick_explainer": "YOUTUBE EXPLAINER",
        "short_explainer": "QUICK EXPLAINER",
    }.get(format_name, "QUICK EXPLAINER")
    small_font, tiny_font = _font(34), _font(28)
    caption_font = _font(38)

    for i in range(frames):
        t = i / FPS
        progress = min(1.0, t / VIDEO_SECONDS)
        scene_index = min(len(scenes) - 1, int(progress * len(scenes)))
        scene_progress = (progress * len(scenes)) % 1.0
        img = Image.new("RGB", (WIDTH, HEIGHT), (7, 9, 18))
        draw = ImageDraw.Draw(img)

        pulse = 0.5 + 0.5 * math.sin(t * 3.2)
        for y in range(0, HEIGHT, 40):
            wave = 0.5 + 0.5 * math.sin(t * 1.7 + y / 130)
            draw.rectangle(
                (0, y, WIDTH, y + 40),
                fill=(
                    int(8 + 12 * wave + 7 * pulse),
                    int(10 + 15 * wave + 5 * pulse),
                    int(24 + 28 * wave + 16 * pulse),
                ),
            )

        # Platform-specific visual language: lists feel structured, TikTok stories feel more kinetic.
        if format_name == "youtube_ranked_breakdown":
            for n in range(5):
                yy = 300 + n * 285
                draw.rounded_rectangle((870, yy, 1005, yy + 92), radius=24, fill=(245, 245, 245))
                draw.text((910, yy + 20), str(n + 1), font=small_font, fill=(7, 9, 18))
        elif format_name == "tiktok_cantina_story":
            for n in range(3):
                x = int(70 + n * 300 + 35 * math.sin(t * 4 + n))
                draw.ellipse((x, 320 + n * 130, x + 70, 390 + n * 130), fill=(245, 245, 245))
        else:
            draw.line((80, 360, WIDTH - 80, 360), fill=(245, 245, 245), width=5)

        # Moving light bands give each scene a more dynamic transition.
        band_x = int((t / VIDEO_SECONDS) * (WIDTH + 500)) - 500
        draw.polygon(
            [(band_x, 0), (band_x + 180, 0), (band_x - 260, HEIGHT), (band_x - 440, HEIGHT)],
            fill=(20, 28, 58),
        )

        format_label = style + " • " + str(
            opportunity.get("format", "quick_explainer")
        ).replace("_", " ").upper()
        badge_width = min(760, 80 + len(format_label) * 22)
        draw.rounded_rectangle((55, 70, badge_width, 150), radius=28, fill=(245, 245, 245))
        draw.text((83, 92), format_label, font=small_font, fill=(7, 9, 18))

        title = script_data.get("title") or opportunity.get("trend", "Trending now")
        y = 235 - min(25, int((1 - min(progress * 5, 1)) * 25))
        for line in _wrap(draw, title, title_font, WIDTH - 140)[:3]:
            draw.text((70, y), line, font=title_font, fill="white")
            y += 92

        hook = script_data.get("hook") or opportunity.get("hook", "")
        draw.rounded_rectangle((60, 555, WIDTH - 60, 760), radius=34, fill=(245, 245, 245))
        draw.text((90, 585), "HOOK", font=tiny_font, fill=(30, 30, 35))
        y = 625
        hook_font = _font(42)
        for line in _wrap(draw, hook, hook_font, WIDTH - 180)[:3]:
            draw.text((90, y), line, font=hook_font, fill=(10, 12, 20))
            y += 52

        # Scene card slides slightly during each transition.
        ease = 0.5 - 0.5 * math.cos(scene_progress * math.pi)
        shift = int(22 * math.sin(t * 2.2) + (1 - ease) * 20)
        top = 875 + shift
        bottom = 1485 + shift
        card_x = int(55 + 10 * math.sin(t * 2.5))
        draw.rounded_rectangle((card_x, top, WIDTH - 55, bottom), radius=42, fill=(6, 8, 16))
        draw.text(
            (90, top + 55),
            f"SCENE {scene_index + 1} • {category.upper()}",
            font=tiny_font,
            fill="white",
        )
        y = top + 125
        for line in _wrap(draw, scenes[scene_index], body_font, WIDTH - 180)[:6]:
            draw.text((90, y), line, font=body_font, fill="white")
            y += 70

        # Large readable karaoke-style caption for the active scene.
        caption = re.sub(r"^(HOOK|WHY IT MATTERS|TAKEAWAY):\s*", "", str(scenes[scene_index]))
        caption_lines = _wrap(draw, caption, caption_font, WIDTH - 170)[:2]
        cap_top = 1510
        cap_bottom = cap_top + 145
        draw.rounded_rectangle((55, cap_top, WIDTH - 55, cap_bottom), radius=28, fill=(245, 245, 245))
        cy = cap_top + 25
        for line in caption_lines:
            draw.text((85, cy), line, font=caption_font, fill=(8, 10, 18))
            cy += 48

        total = max(1, len(scenes))
        start = WIDTH // 2 - ((total - 1) * 22)
        for n in range(total):
            x = start + n * 44
            r = 10 if n == scene_index else 7
            draw.ellipse((x-r, 1685-r, x+r, 1685+r), fill="white")

        draw.rounded_rectangle((65, 1735, WIDTH - 65, 1763), radius=14, fill=(55, 60, 78))
        draw.rounded_rectangle(
            (65, 1735, 65 + int((WIDTH - 130) * progress), 1763),
            radius=14,
            fill="white",
        )
        draw.text((70, 1790), f"{int(progress * 100):02d}%", font=tiny_font, fill="white")
        cta = "WATCH TO THE END" if format_name != "tiktok_cantina_story" else "WAIT FOR THE TWIST"
        draw.text((WIDTH - 350, 1790), cta, font=tiny_font, fill="white")
        draw.text(
            (70, 1850),
            "Follow for more quick trend breakdowns",
            font=small_font,
            fill="white",
        )
        img.save(os.path.join(work, f"frame_{i:05d}.png"))

    silent = os.path.join(OUTPUT_DIR, f"silent_{run_id}.mp4")
    output = os.path.join(OUTPUT_DIR, f"viral_short_{run_id}.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", str(FPS), "-i",
            os.path.join(work, "frame_%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", silent,
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    audio = _make_audio(script_data, output, VIDEO_SECONDS)
    if audio:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", silent, "-i", audio,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart", output,
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        shutil.copy2(silent, output)

    # Keep artifacts small: PNG frames and temporary audio are build intermediates.
    shutil.rmtree(work, ignore_errors=True)
    for temp in [silent, os.path.join(OUTPUT_DIR, "voice.wav"),
                 os.path.join(OUTPUT_DIR, "music.wav"), os.path.join(OUTPUT_DIR, "audio.wav")]:
        if os.path.exists(temp):
            os.remove(temp)

    if not os.path.exists(output) or os.path.getsize(output) < 50_000:
        raise RuntimeError(f"Video quality gate failed: missing or tiny output: {output}")

    manifest = {
        "trend": opportunity["trend"],
        "hook": opportunity["hook"],
        "format": opportunity["format"],
        "duration_seconds": VIDEO_SECONDS,
        "audio": bool(audio),
        "original_content": True,
        "script": script_data,
        "video_file": output,
    }
    with open(
        os.path.join(OUTPUT_DIR, f"latest_video_{run_id}.json"),
        "w", encoding="utf-8"
    ) as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return output


def write_manifest(opportunity, script_data, video_path):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(
        OUTPUT_DIR, f"{os.path.splitext(os.path.basename(video_path))[0]}.json"
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path
