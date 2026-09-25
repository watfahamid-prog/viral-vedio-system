import json
import math
import os
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import OUTPUT_DIR, VIDEO_SECONDS, VIDEO_MIN_SECONDS, VIDEO_MAX_SECONDS

WIDTH, HEIGHT, FPS = 1080, 1920, 15

THEMES = [
    {"bg": (9, 12, 20), "card": (20, 27, 42), "ink": (248, 250, 255), "accent": (70, 220, 190), "hot": (255, 104, 92)},
    {"bg": (20, 10, 30), "card": (42, 22, 55), "ink": (255, 248, 252), "accent": (255, 111, 183), "hot": (255, 196, 74)},
    {"bg": (7, 18, 38), "card": (15, 38, 70), "ink": (244, 248, 255), "accent": (88, 158, 255), "hot": (255, 202, 72)},
]

def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def wrap(draw, text, fnt, width):
    words = str(text).split()
    lines, line = [], ""
    for word in words:
        test = (line + " " + word).strip()
        if draw.textbbox((0, 0), test, font=fnt)[2] <= width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines

def short_phrase(text, max_words=7):
    words = re.findall(r"[A-Za-zÅÄÖåäö0-9’'-]+", str(text))
    return " ".join(words[:max_words]) or "What's happening?"

def duration_for(script, opportunity):
    words = len(str(script.get("script", "")).split())
    est = round(words / 2.5) if words else VIDEO_SECONDS
    if "story" in str(opportunity.get("format", "")).lower():
        est += 4
    return max(VIDEO_MIN_SECONDS, min(VIDEO_MAX_SECONDS, est))

def speech(script):
    text = str(script.get("script", "")).strip()
    if not text:
        text = " ".join(map(str, script.get("scenes", [])))
    return " ".join(text.split())

def make_audio(script, work, duration):
    voice = Path(work) / "voice.wav"
    try:
        subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", "172", "-p", "50", "-a", "160", "-w", str(voice), speech(script)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return str(voice)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

def draw_icon(draw, category, cx, cy, scale, accent, hot):
    cat = str(category).lower()
    if cat == "sports":
        draw.ellipse((cx-scale, cy-scale, cx+scale, cy+scale), outline=accent, width=max(8, scale//14))
        draw.arc((cx-scale//2, cy-scale, cx+scale//2, cy+scale), 25, 155, fill=hot, width=max(6, scale//18))
        draw.arc((cx-scale, cy-scale//2, cx+scale, cy+scale//2), 205, 335, fill=hot, width=max(6, scale//18))
    elif cat == "technology":
        draw.rounded_rectangle((cx-scale, cy-scale, cx+scale, cy+scale), radius=scale//5, outline=accent, width=max(8, scale//14))
        for off in (-scale//2, 0, scale//2):
            draw.line((cx-scale-35, cy+off, cx-scale, cy+off), fill=hot, width=8)
            draw.line((cx+scale, cy+off, cx+scale+35, cy+off), fill=hot, width=8)
        draw.ellipse((cx-scale//3, cy-scale//3, cx+scale//3, cy+scale//3), fill=hot)
    elif cat == "entertainment":
        pts=[]
        for i in range(10):
            a=-math.pi/2+i*math.pi/5
            r=scale if i%2==0 else scale//2
            pts.append((cx+math.cos(a)*r, cy+math.sin(a)*r))
        draw.polygon(pts, fill=accent)
        draw.ellipse((cx-scale//5, cy-scale//5, cx+scale//5, cy+scale//5), fill=hot)
    else:
        for r in (scale, int(scale*.65), int(scale*.3)):
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=accent, width=7)
        draw.ellipse((cx-18, cy-18, cx+18, cy+18), fill=hot)

def render_keyframe(path, title, hook, scene, category, index, total, theme):
    img = Image.new("RGB", (WIDTH, HEIGHT), theme["bg"])
    d = ImageDraw.Draw(img)
    tfont, bfont, sfont = font(76), font(43), font(30)

    # layered abstract motion background
    for k in range(5):
        x = int(WIDTH * (0.18 + 0.16*k) + 35*math.sin(index*1.7+k))
        y = int(300 + 95*math.cos(index*1.1+k))
        r = 190 + 45*k
        d.ellipse((x-r, y-r, x+r, y+r), outline=theme["accent"], width=5)

    d.rounded_rectangle((45, 45, WIDTH-45, HEIGHT-45), radius=55, outline=theme["accent"], width=5)
    d.text((72, 78), "VIRAL BRIEF", font=sfont, fill=theme["accent"])
    d.text((WIDTH-250, 78), f"{index+1:02d}/{total:02d}", font=sfont, fill=theme["ink"])

    # compact title, not a giant repeated paragraph
    title_lines = wrap(d, title, tfont, 820)[:3]
    y=180
    for line in title_lines:
        d.text((72,y), line, font=tfont, fill=theme["ink"])
        y += 88

    draw_icon(d, category, 855, 480, 150, theme["accent"], theme["hot"])

    d.rounded_rectangle((65, 590, WIDTH-65, 865), radius=36, fill=theme["card"])
    d.text((100, 625), "THE HOOK", font=sfont, fill=theme["hot"])
    hook_lines=wrap(d, short_phrase(hook, 10), bfont, WIDTH-210)[:3]
    y=685
    for line in hook_lines:
        d.text((100,y), line, font=bfont, fill=theme["ink"])
        y += 58

    # one clear visual statement per shot
    d.text((70, 955), str(category).upper(), font=sfont, fill=theme["accent"])
    phrase=short_phrase(scene, 6)
    pf=font(102 if len(phrase)<24 else 78)
    lines=wrap(d, phrase, pf, WIDTH-150)[:4]
    y=1030
    for line in lines:
        d.text((70,y), line, font=pf, fill=theme["ink"], stroke_width=1)
        y += 112 if pf.size>90 else 92

    # progress and source cue
    d.rounded_rectangle((70, 1580, WIDTH-70, 1600), radius=10, fill=theme["card"])
    progress=(index+1)/total
    d.rounded_rectangle((70, 1580, int(70+(WIDTH-140)*progress), 1600), radius=10, fill=theme["hot"])
    d.text((70, 1640), "WATCH → UNDERSTAND → SHARE", font=sfont, fill=theme["ink"])
    d.text((70, 1700), "Original visual treatment • no copied footage", font=font(25), fill=theme["accent"])
    img.save(path, quality=94, optimize=True)

def create_video(opportunity, script, index=1):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    slug=re.sub(r"[^a-zA-Z0-9]+","-",str(opportunity.get("trend","trend"))).strip("-").lower()[:45] or "trend"
    run_id=f"{index:02d}-{slug}"
    work=Path(OUTPUT_DIR)/f"v2-{run_id}"
    work.mkdir(parents=True, exist_ok=True)
    duration=duration_for(script, opportunity)
    scenes=[str(x).strip() for x in (script.get("scenes") or [script.get("hook", opportunity.get("trend",""))]) if str(x).strip()]
    target=max(4,min(9,math.ceil(duration/3.2)))
    base=list(scenes)
    while len(scenes)<target:
        scenes.append(base[len(scenes)%len(base)])
    scenes=scenes[:target]
    theme=THEMES[(index-1)%len(THEMES)]
    title=str(script.get("title") or opportunity.get("trend","Current topic"))
    hook=str(script.get("hook") or opportunity.get("hook","Here is what is happening."))
    scene_time=duration/len(scenes)
    keys=[]
    for i,scene in enumerate(scenes):
        p=work/f"key_{i:02d}.jpg"
        render_keyframe(str(p),title,hook,scene,opportunity.get("category","general"),i,len(scenes),theme)
        keys.append(str(p))

    segments=[]
    for i,p in enumerate(keys):
        seg=work/f"seg_{i:02d}.mp4"
        frames=max(1,int(round(scene_time*FPS)))
        direction=1 if i%2==0 else -1
        zoom="min(zoom+0.0011,1.10)"
        x="iw/2-(iw/zoom/2)" if direction>0 else "iw/zoom/2"
        y="ih/2-(ih/zoom/2)"
        subprocess.run([
            "ffmpeg","-y","-loop","1","-i",p,
            "-vf",f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},format=yuv420p",
            "-t",f"{scene_time:.3f}","-an","-c:v","libx264","-preset","veryfast","-crf","22",
            "-movflags","+faststart",str(seg)
        ],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        segments.append(str(seg))

    concat=work/"concat.txt"
    concat.write_text("".join(f"file '{p}'\n" for p in segments),encoding="utf-8")
    silent=work/"silent.mp4"
    out=Path(OUTPUT_DIR)/f"viral_short_v2_{run_id}.mp4"
    # Re-encode the concatenated video instead of stream-copying it. The
    # kinetic renderer can produce tiny per-segment codec/timestamp differences;
    # concat + -c copy then fails with ffmpeg exit 254. Re-encoding normalizes
    # timestamps and codec parameters while keeping the final 1080x1920/15fps
    # output stable for the audio mux and QC stages.
    try:
        subprocess.run([
            "ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),
            "-an","-c:v","libx264","-preset","veryfast","-crf","22",
            "-pix_fmt","yuv420p","-r",str(FPS),"-movflags","+faststart",str(silent)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or "").splitlines()[-25:]
        raise RuntimeError("FFmpeg video assembly failed:\\n" + "\\n".join(tail)) from exc

    audio=make_audio(script,work,duration)
    if audio:
        subprocess.run(["ffmpeg","-y","-i",str(silent),"-i",audio,
                        "-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","128k",
                        "-shortest","-movflags","+faststart",str(out)],
                       check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    else:
        raise RuntimeError("Narration engine unavailable; refusing to publish a silent video.")

    manifest={
        "trend":opportunity.get("trend"),
        "format":opportunity.get("format","short_explainer"),
        "platform":opportunity.get("platform","shorts"),
        "duration_seconds":duration,
        "scene_count":len(scenes),
        "audio":True,
        "original_content":True,
        "visual_engine":"kinetic_motion_v2",
        "theme_index":index-1,
        "script":script,
        "video_file":str(out),
    }
    with open(str(out.with_suffix(".json")),"w",encoding="utf-8") as f:
        json.dump(manifest,f,ensure_ascii=False,indent=2)
    for p in work.iterdir():
        try:p.unlink()
        except OSError:pass
    try:work.rmdir()
    except OSError:pass
    return str(out)

def write_manifest(opportunity, script_data, video_path):
    path=Path(OUTPUT_DIR)/(Path(video_path).stem+".json")
    data={
        "trend":opportunity.get("trend"),
        "hook":opportunity.get("hook"),
        "format":opportunity.get("format","short_explainer"),
        "platform":opportunity.get("platform","shorts"),
        "duration_seconds":duration_for(script_data,opportunity),
        "scene_count":len(script_data.get("scenes",[])),
        "audio":True,
        "original_content":True,
        "script":script_data,
        "video_file":video_path,
    }
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return str(path)
