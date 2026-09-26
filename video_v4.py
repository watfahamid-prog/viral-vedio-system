import json
import math
import os
import re
import subprocess
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
    words = re.findall(r"[A-Za-zÅÄÖåäö0-9’'\-]+", str(text))
    value = " ".join(words[:max_words]).strip()
    return value or "Here is what is happening"

def _slug(text):
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(text)).strip("-").lower()[:45] or "trend"

def _speech(script):
    text = str(script.get("script", "")).strip()
    if not text:
        text = " ".join(map(str, script.get("scenes", [])))
    return " ".join(text.split())

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

def _render_frame(path, title, hook, scene, category, index, total, palette, style):
    bg, ink, accent, hot = palette
    img = Image.new("RGBA", (WIDTH, HEIGHT), (*bg, 255))
    _add_atmosphere(img, accent, hot, index + style * 19)
    d = ImageDraw.Draw(img)

    # Thin cinematic frame and scene marker.
    d.rounded_rectangle((34, 34, WIDTH-34, HEIGHT-34), radius=46, outline=(*accent, 150), width=3)
    d.text((70, 72), "TREND / NOW", font=_font(27), fill=(*accent, 255))
    d.text((WIDTH-210, 72), f"{index+1:02d} / {total:02d}", font=_font(27), fill=(*ink, 235))

    # Every scene has a different composition.
    if index == 0:
        d.text((70, 160), "STOP SCROLLING.", font=_font(70), fill=(*hot, 255))
        y = 265
        for line in _wrap(d, _phrase(hook, 13), _font(88), 900)[:4]:
            d.text((70, y), line, font=_font(88), fill=(*ink, 255))
            y += 105
        _draw_category_icon(d, category, 825, 700, 125, accent, hot)
        d.rounded_rectangle((70, 1050, 1010, 1435), radius=42, fill=(*ink, 18), outline=(*accent, 170), width=3)
        d.text((105, 1105), "WHY THIS MATTERS", font=_font(28), fill=(*accent, 255))
        lines = _wrap(d, _phrase(scene, 22), _font(52), 820)[:5]
        y = 1170
        for line in lines:
            d.text((105, y), line, font=_font(52), fill=(*ink, 255))
            y += 68
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
            d.rounded_rectangle((80, 950, 1000, 1430), radius=46, fill=(*ink, 18), outline=(*accent, 170), width=3)
            d.text((120, 1010), "CONTEXT", font=_font(27), fill=(*accent, 255))
            for j, line in enumerate(_wrap(d, _phrase(hook, 18), _regular(43), 790)[:5]):
                d.text((120, 1080 + j*62), line, font=_regular(43), fill=(*ink, 225))
        elif layouts == 1:
            d.rounded_rectangle((60, 160, 1020, 820), radius=54, fill=(*accent, 235))
            d.text((105, 215), "WHAT CHANGED?", font=_font(30), fill=(*bg, 255))
            y = 300
            for line in _wrap(d, _phrase(scene, 15), _font(80), 820)[:5]:
                d.text((105, y), line, font=_font(80), fill=(*bg, 255))
                y += 94
            d.text((75, 950), "WATCH THE REACTION", font=_font(29), fill=(*hot, 255))
            _draw_category_icon(d, category, 820, 1280, 190, accent, hot)
        elif layouts == 2:
            d.text((70, 165), "ZOOM IN", font=_font(30), fill=(*accent, 255))
            d.ellipse((720, 190, 1010, 480), outline=(*hot, 220), width=10)
            d.ellipse((790, 260, 940, 410), fill=(*accent, 80), outline=(*accent, 255), width=4)
            y = 550
            for line in _wrap(d, _phrase(scene, 17), _font(78), 900)[:5]:
                d.text((70, y), line, font=_font(78), fill=(*ink, 255))
                y += 94
            d.line((70, 1110, 1010, 1110), fill=(*accent, 180), width=4)
            d.text((70, 1170), "THE QUICK VERSION", font=_font(29), fill=(*hot, 255))
            for j, line in enumerate(_wrap(d, _phrase(hook, 16), _regular(45), 880)[:4]):
                d.text((70, 1230+j*63), line, font=_regular(45), fill=(*ink, 225))
        else:
            d.text((70, 160), "BREAKDOWN", font=_font(30), fill=(*hot, 255))
            d.rounded_rectangle((70, 235, 1010, 625), radius=48, fill=(*ink, 16), outline=(*accent, 170), width=3)
            d.text((110, 285), "01", font=_font(90), fill=(*accent, 255))
            d.text((275, 305), _phrase(scene, 7), font=_font(58), fill=(*ink, 255))
            d.line((110, 700, 970, 700), fill=(*accent, 170), width=4)
            d.text((110, 770), "AND HERE IS WHY", font=_font(29), fill=(*hot, 255))
            y = 840
            for line in _wrap(d, _phrase(hook, 18), _font(62), 840)[:6]:
                d.text((110, y), line, font=_font(62), fill=(*ink, 255))
                y += 78

    # Persistent but subtle progress indicator.
    bar_y = 1740
    d.rounded_rectangle((70, bar_y, 1010, bar_y+12), radius=6, fill=(*ink, 45))
    progress = (index + 1) / total
    d.rounded_rectangle((70, bar_y, int(70 + 940*progress), bar_y+12), radius=6, fill=(*hot, 255))
    d.text((70, 1790), _phrase(title, 9).upper(), font=_font(25), fill=(*ink, 175))
    img.convert("RGB").save(path, quality=95, optimize=True)

def _make_audio(script, work, duration):
    voice = Path(work) / "voice.wav"
    try:
        subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", "178", "-p", "48", "-a", "155", "-w", str(voice), _speech(script)],
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
    path = Path(work) / "captions.ass"
    scenes = [str(x).strip() for x in (script.get("scenes") or []) if str(x).strip()]
    if not scenes:
        scenes = [str(script.get("hook", ""))]
    weights = [max(1, len(s.split())) for s in scenes]
    total = sum(weights) or 1

    def stamp(value):
        cs = int((value - int(value)) * 100)
        return f"0:{int(value)//60:02d}:{int(value)%60:02d}.{cs:02d}"

    def esc(value):
        return str(value).replace("\\", "\\\\").replace("{", "\{").replace("}", "\}")

    with path.open("w", encoding="utf-8") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n")
        f.write("[V4+ Styles]\n")
        f.write("Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n")
        f.write("Style: Viral,DejaVu Sans,48,&H00FFFFFF,&H00FFFFFF,&H00101010,&HAA101010,-1,0,0,0,100,100,0,0,3,3,1,2,80,80,230,1\n\n")
        f.write("[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
        cursor = 0.0
        for i, scene in enumerate(scenes):
            step = duration * weights[i] / total
            start, end = cursor, min(duration, cursor + step)
            cursor = end
            words = scene.split()
            if len(words) > 10:
                mid = len(words) // 2
                scene = " ".join(words[:mid]) + "\\N" + " ".join(words[mid:])
            f.write(f"Dialogue: 0,{stamp(start)},{stamp(end)},Viral,,0,0,0,,{esc(scene)}\n")
    return str(path)

def _build_segment(keyframe, output, seconds, direction, first=False, last=False):
    frames = max(1, int(round(seconds * FPS)))
    zoom = "min(zoom+0.0014,1.12)" if direction > 0 else "min(zoom+0.0012,1.10)"
    if direction > 0:
        x = "iw/2-(iw/zoom/2)"
    else:
        x = "iw/zoom/2"
    y = "ih/2-(ih/zoom/2)"
    vf = (
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        "format=yuv420p,"
        + ("fade=t=in:st=0:d=0.18," if first else "")
        + (f"fade=t=out:st={max(0, seconds-0.18):.3f}:d=0.18" if last else "")
    )
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", keyframe,
        "-vf", vf, "-t", f"{seconds:.3f}",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", output
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    target = max(6, min(10, math.ceil(duration / 2.6)))
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

    keys = []
    for i, scene in enumerate(scenes):
        key = work / f"key_{i:02d}.jpg"
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
        "format": opportunity.get("format", "short_explainer"),
        "platform": opportunity.get("platform", "shorts"),
        "duration_seconds": duration,
        "scene_count": len(scenes),
        "audio": True,
        "captions": True,
        "original_content": True,
        "visual_engine": "kinetic_motion_v4_optional_ai_hero",
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
        "visual_engine": "kinetic_motion_v4",
        "script": script_data,
        "video_file": video_path,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
