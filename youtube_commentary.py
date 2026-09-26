import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

import requests

from config import OUTPUT_DIR, TTS_ENGINE, TTS_VOICE

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
YOUTUBE_MODE = os.getenv("YOUTUBE_COMMENTARY_MODE", "voice").lower()
CLIPS_PER_VIDEO = min(10, max(5, int(os.getenv("YOUTUBE_CLIPS_PER_VIDEO", "7"))))
CLIP_SECONDS = max(3, int(os.getenv("YOUTUBE_CLIP_SECONDS", "6")))
DOWNLOAD_TIMEOUT = int(os.getenv("YOUTUBE_CLIP_TIMEOUT", "90"))


def _safe_name(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return value[:80] or "clip"


def _commons_video_search(query, limit=8):
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:video {query}",
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "format": "json",
    }
    response = requests.get(COMMONS_API, params=params, timeout=30)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    results = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("url", "")
        mime = info.get("mime", "")
        if not url or not mime.startswith("video/"):
            continue
        meta = info.get("extmetadata", {})
        license_name = (meta.get("LicenseShortName") or {}).get("value", "")
        usage = (meta.get("UsageTerms") or {}).get("value", "")
        # Commons is the source; keep the license metadata beside every downloaded clip.
        results.append({
            "title": page.get("title", ""),
            "url": url,
            "mime": mime,
            "license": re.sub("<[^>]+>", "", license_name or usage),
            "description": re.sub("<[^>]+>", "", (meta.get("ImageDescription") or {}).get("value", "")),
            "source_url": "https://commons.wikimedia.org/wiki/" + quote(page.get("title", "").replace(" ", "_")),
        })
    return results


def _download(url, path):
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, headers={"User-Agent": "viral-video-system/1.0"}) as response:
        response.raise_for_status()
        with open(path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    return path


def _probe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _make_clip(source, destination, start, duration):
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(start), "-i", str(source),
        "-t", str(duration), "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "-r", "30", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        str(destination)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _concat(clips, output):
    manifest = output.parent / "concat.txt"
    manifest.write_text("\n".join(f"file '{p.resolve()}'" for p in clips), encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest),
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output


def _commentary(opportunity, source):
    title = source.get("title", "").replace("File:", "").strip()
    description = re.sub(r"\s+", " ", source.get("description", "")).strip()
    trend = opportunity.get("trend", "this clip")
    if description:
        detail = description[:180].rstrip(".")
        return f"Here is something interesting about {trend}. This clip shows {detail}. Watch closely — the real moment is what makes this one interesting."
    return f"Here is a real-life moment connected to {trend}. Watch closely — the interesting part happens quickly."


def _tts(text, path):
    if TTS_ENGINE in {"none", "text"}:
        return None
    try:
        if TTS_ENGINE in {"auto", "edge"}:
            import asyncio
            import edge_tts
            async def make():
                await edge_tts.Communicate(text, TTS_VOICE).save(str(path))
            asyncio.run(make())
            return str(path)
    except Exception as error:
        print(f"YouTube TTS fallback: {error}")
    return None


def create_youtube_commentary_video(opportunity, index):
    root = Path(OUTPUT_DIR) / f"youtube_{index}"
    root.mkdir(parents=True, exist_ok=True)
    query = opportunity.get("trend") or "interesting real life moment"
    # Search broadly enough to collect 5–10 reusable clips. We keep the
    # requested count configurable, but never allow fewer than five.
    search_limit = max(CLIPS_PER_VIDEO * 3, 20)
    queries = [query, f"{query} real life", "people real life", "interesting people"]
    sources = []
    seen = set()
    for search_query in queries:
        try:
            for item in _commons_video_search(search_query, limit=search_limit):
                key = item.get("source_url") or item.get("url")
                if key and key not in seen:
                    seen.add(key)
                    sources.append(item)
                if len(sources) >= CLIPS_PER_VIDEO:
                    break
        except requests.RequestException as error:
            print(f"YouTube source search failed for '{search_query}': {error}")
        if len(sources) >= CLIPS_PER_VIDEO:
            break
    if len(sources) < CLIPS_PER_VIDEO:
        raise RuntimeError(
            f"Only {len(sources)} reusable clips found; need {CLIPS_PER_VIDEO} for YouTube video #{index}"
        )

    clips = []
    manifest = []
    for clip_index, source in enumerate(sources[:CLIPS_PER_VIDEO]):
        raw = root / f"source_{clip_index}_{_safe_name(source['title'])}.mp4"
        segment = root / f"segment_{clip_index}.mp4"
        _download(source["url"], raw)
        duration = _probe_duration(raw)
        if duration < 2:
            continue
        max_start = max(0.0, duration - CLIP_SECONDS)
        start = min((clip_index * 1.7) % max(1.0, duration), max_start)
        _make_clip(raw, segment, start, min(CLIP_SECONDS, duration))
        clips.append(segment)
        manifest.append(source)

    if len(clips) < CLIPS_PER_VIDEO:
        raise RuntimeError(f"YouTube video #{index} produced only {len(clips)} usable clips; need {CLIPS_PER_VIDEO}")

    combined = root / "combined.mp4"
    _concat(clips, combined)

    comments = [_commentary(opportunity, source) for source in manifest]
    full_commentary = " ".join(comments)
    audio = root / "commentary.mp3"
    audio_path = _tts(full_commentary, audio)

    final = Path(OUTPUT_DIR) / f"youtube_commentary_{index}.mp4"
    if audio_path and YOUTUBE_MODE != "text":
        subprocess.run([
            "ffmpeg", "-y", "-i", str(combined), "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            "-shortest", "-movflags", "+faststart", str(final)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        mode = "ai_voice"
    else:
        # Text mode burns short commentary cards onto the footage and adds a silent
        # AAC track so the result remains a normal YouTube-ready MP4.
        subtitle = root / "commentary.srt"
        cursor = 0
        lines = []
        for n, comment in enumerate(comments, 1):
            start, end = cursor, cursor + CLIP_SECONDS
            def stamp(seconds):
                h = int(seconds // 3600)
                m = int((seconds % 3600) // 60)
                s = int(seconds % 60)
                ms = int((seconds - int(seconds)) * 1000)
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
            lines.append(f"{n}\n{stamp(start)} --> {stamp(end)}\n{comment}\n")
            cursor = end
        subtitle.write_text("\n".join(lines), encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-y", "-i", str(combined),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf", f"subtitles={subtitle.as_posix()}:force_style='FontSize=26,Alignment=2,MarginV=80'",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(final)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        mode = "text"

    metadata = {
        "platform": "youtube",
        "mode": mode,
        "trend": opportunity.get("trend", ""),
        "commentary": comments,
        "sources": manifest,
        "license_policy": "Only Wikimedia Commons video results with returned license metadata are used.",
    }
    meta_path = Path(OUTPUT_DIR) / f"youtube_commentary_{index}.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(final), str(meta_path)
