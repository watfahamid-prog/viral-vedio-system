import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFont
from config import OUTPUT_DIR, VIDEO_SECONDS, VIDEO_MIN_SECONDS, VIDEO_MAX_SECONDS, VIDEO_ENGINE, COMFYUI_URL, TTS_ENGINE, TTS_VOICE, AI_VIDEO_MAX_CLIPS
from ai_video import generate_clip, engine_available

WIDTH, HEIGHT, FPS = 1080, 1920, 15

PALETTES = [
    {"name": "editorial", "bg": (246, 243, 238), "panel": (255, 255, 255), "ink": (24, 24, 24),
     "muted": (105, 100, 94), "accent": (211, 72, 45), "accent2": (244, 183, 64)},
    {"name": "sunset", "bg": (35, 18, 28), "panel": (57, 27, 39), "ink": (255, 248, 239),
     "muted": (210, 177, 181), "accent": (255, 111, 97), "accent2": (255, 197, 90)},
    {"name": "mint", "bg": (232, 241, 235), "panel": (250, 252, 248), "ink": (20, 35, 28),
     "muted": (91, 112, 99), "accent": (39, 117, 92), "accent2": (225, 154, 72)},
    {"name": "midnight", "bg": (16, 20, 30), "panel": (30, 38, 54), "ink": (245, 248, 255),
     "muted": (163, 174, 195), "accent": (92, 157, 255), "accent2": (255, 196, 87)},
    {"name": "paper", "bg": (238, 236, 229), "panel": (250, 249, 245), "ink": (32, 34, 39),
     "muted": (104, 105, 110), "accent": (111, 79, 190), "accent2": (220, 120, 70)},
]


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
    speech = _clean_speech(script_data)
    if not speech:
        return None
    work = os.path.dirname(output)
    voice = os.path.join(work, "voice.mp3")
    music = os.path.join(work, "music.wav")
    mixed = os.path.join(work, "audio.wav")
    try:
        if TTS_ENGINE == "edge":
            subprocess.run(
                ["edge-tts", "--voice", TTS_VOICE, "--rate=+8%", "--text", speech, "--write-media", voice],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            voice = os.path.join(work, "voice.wav")
            subprocess.run(
                ["espeak-ng", "-v", "en-us", "-s", "172", "-p", "48", "-a", "155", "-w", voice, speech],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=92:duration={duration}",
             "-filter_complex", f"[0:a]volume=0.025,afade=t=in:st=0:d=1,afade=t=out:st={max(0,duration-1)}:d=1[m]",
             "-c:a", "pcm_s16le", music],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", voice, "-i", music,
             "-filter_complex",
             "[0:a]atrim=0:{0},asetpts=N/SR/TB,volume=1.0[v];"
             "[1:a]atrim=0:{0},asetpts=N/SR/TB[m];"
             "[v][m]amix=inputs=2:duration=longest:dropout_transition=0,"
             "loudnorm=I=-16:TP=-1.5:LRA=11[a]".format(duration),
             "-map", "[a]", "-t", str(duration), "-c:a", "pcm_s16le", mixed],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return mixed
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _draw_editorial(draw, p, title, hook, scene, category, scene_index, total, progress, t, fonts):
    title_font, body_font, small_font = fonts
    draw.text((70, 75), "TREND BRIEF", font=small_font, fill=p["accent"])
    draw.line((70, 135, WIDTH - 70, 135), fill=p["ink"], width=4)
    y = 185
    for line in _wrap(draw, title, title_font, WIDTH - 140)[:3]:
        draw.text((70, y), line, font=title_font, fill=p["ink"])
        y += 92
    draw.rounded_rectangle((70, 510, WIDTH - 70, 755), radius=28, fill=p["panel"], outline=p["accent"], width=4)
    draw.text((100, 545), "THE HOOK", font=small_font, fill=p["accent"])
    y = 605
    for line in _wrap(draw, hook, body_font, WIDTH - 200)[:3]:
        draw.text((100, y), line, font=body_font, fill=p["ink"])
        y += 58
    draw.rounded_rectangle((70, 850, WIDTH - 70, 1420), radius=32, fill=p["ink"])
    draw.text((105, 895), f"{category.upper()}  /  {scene_index + 1:02d}", font=small_font, fill=p["accent2"])
    y = 980
    for line in _wrap(draw, scene, body_font, WIDTH - 210)[:7]:
        draw.text((105, y), line, font=body_font, fill=p["bg"])
        y += 66
    draw.text((70, 1510), "ORIGINAL QUICK BREAKDOWN", font=small_font, fill=p["muted"])


def _draw_sunset(draw, p, title, hook, scene, category, scene_index, total, progress, t, fonts):
    title_font, body_font, small_font = fonts
    for r in [170, 330, 490]:
        cx = int(820 + 80 * math.sin(t * 1.4))
        cy = int(280 + 70 * math.cos(t * 1.2))
        draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=p["accent"], width=6)
    draw.text((65, 75), "STORY MODE", font=small_font, fill=p["accent2"])
    y = 180
    for line in _wrap(draw, title, title_font, 900)[:3]:
        draw.text((65, y), line, font=title_font, fill=p["ink"])
        y += 90
    draw.rounded_rectangle((65, 540, WIDTH - 65, 770), radius=45, fill=p["accent"])
    draw.text((100, 580), "WAIT —", font=small_font, fill=p["bg"])
    y = 635
    for line in _wrap(draw, hook, body_font, WIDTH - 200)[:3]:
        draw.text((100, y), line, font=body_font, fill=p["bg"])
        y += 55
    draw.rounded_rectangle((65, 875, WIDTH - 65, 1450), radius=45, fill=p["panel"])
    draw.text((105, 925), f"{scene_index + 1}/{total}  •  {category.upper()}", font=small_font, fill=p["accent"])
    y = 1010
    for line in _wrap(draw, scene, body_font, WIDTH - 210)[:7]:
        draw.text((105, y), line, font=body_font, fill=p["ink"])
        y += 66
    draw.text((65, 1535), "FOLLOW FOR THE NEXT STORY", font=small_font, fill=p["accent2"])


def _draw_mint(draw, p, title, hook, scene, category, scene_index, total, progress, t, fonts):
    title_font, body_font, small_font = fonts
    draw.rounded_rectangle((45, 45, WIDTH - 45, HEIGHT - 45), radius=55, outline=p["accent"], width=6)
    draw.ellipse((760, 90, 1010, 340), fill=p["accent2"])
    draw.ellipse((835, 165, 935, 265), fill=p["panel"])
    draw.text((85, 90), "EXPLAINED", font=small_font, fill=p["accent"])
    y = 190
    for line in _wrap(draw, title, title_font, 760)[:3]:
        draw.text((85, y), line, font=title_font, fill=p["ink"])
        y += 92
    draw.text((85, 520), "WHY PEOPLE CARE", font=small_font, fill=p["accent"])
    y = 585
    for line in _wrap(draw, hook, body_font, WIDTH - 170)[:3]:
        draw.text((85, y), line, font=body_font, fill=p["ink"])
        y += 58
    draw.rounded_rectangle((85, 820, WIDTH - 85, 1435), radius=38, fill=p["panel"])
    draw.text((125, 875), f"STEP {scene_index + 1}", font=small_font, fill=p["accent"])
    y = 955
    for line in _wrap(draw, scene, body_font, WIDTH - 250)[:7]:
        draw.text((125, y), line, font=body_font, fill=p["ink"])
        y += 66
    draw.text((85, 1515), f"{category.upper()}  •  {int(progress * 100):02d}%", font=small_font, fill=p["muted"])


def _visual_prompt(opportunity, scene):
    trend = str(opportunity.get("trend", "current topic"))
    category = str(opportunity.get("category", "general"))
    return (
        f"Vertical social media video, cinematic documentary style, {category} topic. "
        f"Visualize this current topic without text, logos, watermarks, or recognizable copyrighted characters: "
        f"{trend}. Scene: {scene}. Natural motion, realistic lighting, strong composition, fast social-media pacing, "
        f"visually interesting background, coherent subject, 9:16."
    )


def _make_ai_visuals(opportunity, script_data, duration, run_id):
    if not engine_available():
        return None
    scenes = script_data.get("scenes") or [script_data.get("hook", opportunity.get("trend", ""))]
    clip_dir = os.path.join(OUTPUT_DIR, f"ai-clips-{run_id}")
    os.makedirs(clip_dir, exist_ok=True)
    clips = []
    for i, scene in enumerate(scenes[:max(1, AI_VIDEO_MAX_CLIPS)]):
        path = os.path.join(clip_dir, f"clip_{i:02d}.mp4")
        if generate_clip(_visual_prompt(opportunity, scene), path, duration=5):
            clips.append(path)
    if not clips:
        shutil.rmtree(clip_dir, ignore_errors=True)
        return None

    concat_list = os.path.join(clip_dir, "concat.txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for clip in clips:
            f.write(f"file '{os.path.abspath(clip)}'\n")

    visual = os.path.join(OUTPUT_DIR, f"ai_visuals_{run_id}.mp4")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-stream_loop", "-1", "-f", "concat", "-safe", "0", "-i", concat_list,
             "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},setsar=1",
             "-t", str(duration), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", visual],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return visual
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    finally:
        shutil.rmtree(clip_dir, ignore_errors=True)

def _make_srt(script_data, duration, run_id):
    path = os.path.join(OUTPUT_DIR, f"captions-{run_id}.srt")
    scenes = script_data.get("scenes") or [script_data.get("hook", "")]
    step = duration / max(1, len(scenes))
    with open(path, "w", encoding="utf-8") as f:
        for i, scene in enumerate(scenes):
            start = i * step
            end = min(duration, (i + 1) * step)
            def stamp(value):
                hours = int(value // 3600)
                minutes = int((value % 3600) // 60)
                seconds = int(value % 60)
                millis = int((value - int(value)) * 1000)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
            f.write(f"{i + 1}\n{stamp(start)} --> {stamp(end)}\n{str(scene).strip()}\n\n")
    return path

def _choose_duration(script_data, opportunity):
    """Choose a trend-dependent duration between the configured minimum and maximum."""
    text = _clean_speech(script_data)
    words = len(re.findall(r"\b\w+[\w'’-]*\b", text))
    estimated = int(round(words / 2.3)) if words else VIDEO_SECONDS
    fmt = str(opportunity.get("format", "")).lower()
    if "story" in fmt:
        estimated += 8
    elif "quick" in fmt:
        estimated -= 5
    return max(VIDEO_MIN_SECONDS, min(VIDEO_MAX_SECONDS, estimated))


def create_video(opportunity, script_data, index=1):
    """Build a fast, polished vertical video.

    The default renderer uses a handful of high-resolution scene cards plus
    ffmpeg motion (zoom/pan). This is dramatically faster than rendering one
    1080x1920 PNG for every frame. Remote AI video is optional and capped so
    a provider outage can never stall the whole automation.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    run_id = f"{index:02d}-{_slug(opportunity.get('trend', 'trend'))}"
    work = os.path.join(OUTPUT_DIR, f"render-{run_id}")
    os.makedirs(work, exist_ok=True)

    duration = _choose_duration(script_data, opportunity)
    scenes = script_data.get("scenes") or [script_data.get("hook", opportunity["hook"])]
    scenes = [str(s).strip() for s in scenes if str(s).strip()][:5]
    if not scenes:
        scenes = [str(opportunity.get("hook", opportunity.get("trend", "Current topic")))]

    title_font, body_font, small_font = _font(72), _font(42), _font(31)
    style_seed = hashlib.sha256(str(opportunity.get("trend", "")).encode("utf-8")).hexdigest()
    palette = PALETTES[int(style_seed[:8], 16) % len(PALETTES)]
    fonts = (title_font, body_font, small_font)

    # One keyframe per scene instead of hundreds/thousands of PNG frames.
    keyframes = []
    scene_duration = duration / len(scenes)
    for scene_index, scene in enumerate(scenes):
        img = Image.new("RGB", (WIDTH, HEIGHT), palette["bg"])
        draw = ImageDraw.Draw(img)
        progress = scene_index / max(1, len(scenes) - 1)
        args = (
            draw, palette, script_data.get("title", opportunity["trend"]),
            script_data.get("hook", opportunity["hook"]), scene,
            opportunity.get("category", "general"), scene_index, len(scenes),
            progress, scene_index * scene_duration, fonts
        )
        if index % 3 == 1:
            _draw_editorial(*args)
        elif index % 3 == 2:
            _draw_sunset(*args)
        else:
            _draw_mint(*args)

        # Large kinetic caption area for readability on phones.
        caption = re.sub(r"\s+", " ", scene)
        caption_lines = _wrap(draw, caption, body_font, WIDTH - 170)[:3]
        cap_y = 1540
        for line in caption_lines:
            draw.rounded_rectangle(
                (65, cap_y - 8, WIDTH - 65, cap_y + 50),
                radius=16, fill=palette["ink"]
            )
            draw.text((85, cap_y), line, font=small_font, fill=palette["bg"])
            cap_y += 54

        path = os.path.join(work, f"scene_{scene_index:02d}.jpg")
        img.save(path, quality=92, optimize=True)
        keyframes.append(path)

    silent = os.path.join(OUTPUT_DIR, f"silent_{run_id}.mp4")
    output = os.path.join(OUTPUT_DIR, f"viral_short_{run_id}.mp4")

    # Turn each keyframe into a subtle moving shot, then join the shots.
    segments = []
    for i, image_path in enumerate(keyframes):
        segment = os.path.join(work, f"segment_{i:02d}.mp4")
        seg_duration = scene_duration
        frames = max(1, int(round(seg_duration * FPS)))
        zoom = "min(zoom+0.0009,1.08)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
        subprocess.run(
            [
                "ffmpeg", "-y", "-loop", "1", "-i", image_path,
                "-vf",
                f"zoompan=z='{zoom}':x='{x_expr}':y='{y_expr}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}",
                "-t", f"{seg_duration:.3f}", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", segment
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        segments.append(segment)

    concat_list = os.path.join(work, "segments.txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for segment in segments:
            f.write(f"file '{os.path.abspath(segment)}'\n")

    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c", "copy", "-movflags", "+faststart", silent],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Optional AI footage. Disabled in the GitHub workflow by default because
    # remote text-to-video can be slow; if enabled, use only a small number of
    # clips and fall back instantly to the fast renderer.
    ai_visuals = None
    if engine_available() and AI_VIDEO_MAX_CLIPS > 0:
        ai_visuals = _make_ai_visuals(opportunity, script_data, duration, run_id)

    subtitle_file = _make_srt(script_data, duration, run_id) if ai_visuals else None
    visual_source = ai_visuals or silent
    captioned = None

    if ai_visuals and subtitle_file:
        captioned = os.path.join(OUTPUT_DIR, f"captioned_{run_id}.mp4")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", ai_visuals, "-vf", f"subtitles={subtitle_file}",
                 "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", captioned],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            visual_source = captioned
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    audio = _make_audio(script_data, output, duration)
    if audio:
        subprocess.run(
            ["ffmpeg", "-y", "-i", visual_source, "-i", audio,
             "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
             "-shortest", "-movflags", "+faststart", output],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        shutil.copy2(visual_source, output)

    shutil.rmtree(work, ignore_errors=True)
    for temp in [
        silent, ai_visuals, subtitle_file,
        captioned if "captioned" in locals() else None,
        os.path.join(OUTPUT_DIR, "voice.wav"),
        os.path.join(OUTPUT_DIR, "voice.mp3"),
        os.path.join(OUTPUT_DIR, "music.wav"),
        os.path.join(OUTPUT_DIR, "audio.wav"),
    ]:
        if temp and os.path.exists(temp):
            os.remove(temp)

    if not os.path.exists(output) or os.path.getsize(output) < 50_000:
        raise RuntimeError(f"Video quality gate failed: missing or tiny output: {output}")

    manifest = {
        "trend": opportunity["trend"],
        "hook": opportunity["hook"],
        "format": opportunity.get("format", "short_explainer"),
        "platform": opportunity.get("platform", "shorts"),
        "style": palette["name"],
        "confidence": opportunity.get("confidence", 0),
        "duration_seconds": duration,
        "scene_count": len(scenes),
        "audio": bool(audio),
        "original_content": True,
        "script": script_data,
        "video_file": output,
        "video_engine": "motion_graphics" if not ai_visuals else VIDEO_ENGINE,
        "ai_video_used": bool(ai_visuals),
        "ai_engine_ready": engine_available(),
        "ai_model": os.getenv("AI_VIDEO_MODEL", ""),
        "comfyui_configured": bool(COMFYUI_URL),
    }
    with open(os.path.join(OUTPUT_DIR, f"latest_video_{run_id}.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return output


def write_manifest(opportunity, script_data, video_path):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{os.path.splitext(os.path.basename(video_path))[0]}.json")
    manifest = {
        "trend": opportunity["trend"], "hook": opportunity["hook"],
        "format": opportunity.get("format", "short_explainer"),
        "platform": opportunity.get("platform", "shorts"),
        "duration_seconds": _choose_duration(script_data, opportunity), "original_content": True,
        "script": script_data, "video_file": video_path,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path
