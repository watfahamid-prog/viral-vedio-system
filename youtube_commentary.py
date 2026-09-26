import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import requests

from config import OUTPUT_DIR, TTS_ENGINE, TTS_VOICE

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
PEXELS_API = "https://api.pexels.com/v1/videos/search"
PIXABAY_API = "https://pixabay.com/api/videos/"
IA_ADVANCEDSEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/{identifier}"

YOUTUBE_MODE = os.getenv("YOUTUBE_COMMENTARY_MODE", "voice").lower()
CLIPS_PER_VIDEO = min(10, max(5, int(os.getenv("YOUTUBE_CLIPS_PER_VIDEO", "10"))))
CLIP_SECONDS = max(3, int(os.getenv("YOUTUBE_CLIP_SECONDS", "5")))
DOWNLOAD_TIMEOUT = int(os.getenv("YOUTUBE_CLIP_TIMEOUT", "90"))
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
IA_ENABLED = os.getenv("INTERNET_ARCHIVE_ENABLED", "true").lower() == "true"
ELEVENLABS_ENABLED = os.getenv("ELEVENLABS_ENABLED", "false").lower() == "true"
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb").strip()
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5").strip()


def _safe_name(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return value[:80] or "clip"


def _clean(value):
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


def _commons_video_search(query, limit=8):
    params = {
        "action": "query", "generator": "search",
        "gsrsearch": f"filetype:video {query}", "gsrnamespace": 6,
        "gsrlimit": limit, "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata", "format": "json",
    }
    response = requests.get(
        COMMONS_API, params=params,
        headers={"User-Agent": "ViralVideoAutomationBot/1.0 (Wikimedia Commons)"},
        timeout=30,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    results = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url, mime = info.get("url", ""), info.get("mime", "")
        if not url or not mime.startswith("video/"):
            continue
        meta = info.get("extmetadata", {})
        license_name = _clean((meta.get("LicenseShortName") or {}).get("value", ""))
        usage = _clean((meta.get("UsageTerms") or {}).get("value", ""))
        if not license_name and not usage:
            continue
        results.append({
            "title": page.get("title", ""),
            "url": url, "mime": mime,
            "license": license_name or usage,
            "description": _clean((meta.get("ImageDescription") or {}).get("value", "")),
            "source_url": "https://commons.wikimedia.org/wiki/" + quote(page.get("title", "").replace(" ", "_")),
            "provider": "Wikimedia Commons",
        })
    return results


def _pexels_video_search(query, limit=15):
    if not PEXELS_API_KEY:
        return []
    response = requests.get(
        PEXELS_API, params={"query": query, "per_page": min(limit, 80)},
        headers={"Authorization": PEXELS_API_KEY, "User-Agent": "ViralVideoAutomationBot/1.0"},
        timeout=30,
    )
    response.raise_for_status()
    results = []
    for item in response.json().get("videos", []):
        files = [x for x in item.get("video_files", []) if x.get("link")]
        files.sort(key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True)
        if not files:
            continue
        chosen = next((x for x in files if (x.get("width") or 0) >= 1280), files[0])
        results.append({
            "title": item.get("url", "Pexels video").rstrip("/").split("/")[-1],
            "url": chosen["link"], "mime": "video/mp4",
            "license": "Pexels License",
            "description": _clean(item.get("user", {}).get("name", "")),
            "source_url": item.get("url", ""),
            "provider": "Pexels",
            "creator": item.get("user", {}).get("name", ""),
        })
    return results


def _pixabay_video_search(query, limit=15):
    if not PIXABAY_API_KEY:
        return []
    response = requests.get(
        PIXABAY_API, params={"key": PIXABAY_API_KEY, "q": query, "per_page": min(limit, 200)},
        headers={"User-Agent": "ViralVideoAutomationBot/1.0"},
        timeout=30,
    )
    response.raise_for_status()
    results = []
    for item in response.json().get("hits", []):
        videos = item.get("videos", {})
        candidates = [v for v in videos.values() if isinstance(v, dict) and v.get("url")]
        candidates.sort(key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True)
        if not candidates:
            continue
        chosen = next((x for x in candidates if (x.get("width") or 0) >= 1280), candidates[0])
        results.append({
            "title": item.get("tags", "Pixabay video"),
            "url": chosen["url"], "mime": "video/mp4",
            "license": "Pixabay Content License",
            "description": item.get("tags", ""),
            "source_url": item.get("pageURL", ""),
            "provider": "Pixabay",
            "creator": item.get("user", ""),
        })
    return results


def _internet_archive_video_search(query, limit=15):
    if not IA_ENABLED:
        return []
    params = {
        "q": f'({query}) AND mediatype:movies',
        "fl[]": ["identifier", "title", "description", "licenseurl"],
        "rows": min(limit, 50), "page": 1, "output": "json",
    }
    response = requests.get(IA_ADVANCEDSEARCH, params=params, timeout=30)
    response.raise_for_status()
    docs = response.json().get("response", {}).get("docs", [])
    results = []
    allowed_terms = ("creativecommons.org/licenses/", "publicdomain", "cc0")
    for doc in docs:
        identifier = doc.get("identifier")
        license_url = str(doc.get("licenseurl") or "").lower()
        if not identifier or not any(term in license_url for term in allowed_terms):
            continue
        metadata_url = IA_METADATA.format(identifier=quote(identifier))
        try:
            meta_response = requests.get(metadata_url, timeout=30)
            meta_response.raise_for_status()
            files = meta_response.json().get("files", [])
        except requests.RequestException:
            continue
        candidates = []
        for item in files:
            name = str(item.get("name", ""))
            fmt = str(item.get("format", "")).lower()
            if name.lower().endswith((".mp4", ".webm", ".mov", ".m4v")) or "mpeg" in fmt or "webm" in fmt:
                size = int(item.get("size") or 0) if str(item.get("size") or "").isdigit() else 0
                candidates.append((size, name))
        candidates.sort(reverse=True)
        if not candidates:
            continue
        name = candidates[0][1]
        results.append({
            "title": doc.get("title") or identifier,
            "url": f"https://archive.org/download/{quote(identifier)}/{quote(name)}",
            "mime": "video/mp4",
            "license": doc.get("licenseurl", ""),
            "description": _clean(doc.get("description", "")),
            "source_url": f"https://archive.org/details/{quote(identifier)}",
            "provider": "Internet Archive",
        })
    return results


def _search_sources(query, limit):
    # Ordered fallback: Commons first, then API-backed stock libraries, then Internet Archive.
    providers = [
        ("Wikimedia Commons", _commons_video_search),
        ("Pexels", _pexels_video_search),
        ("Pixabay", _pixabay_video_search),
        ("Internet Archive", _internet_archive_video_search),
    ]
    all_results = []
    for provider, searcher in providers:
        try:
            found = searcher(query, limit=limit)
            print(f"YouTube source search: {provider} returned {len(found)} candidates.")
            all_results.extend(found)
        except requests.RequestException as error:
            print(f"YouTube source search failed for {provider}: {error}")
        except Exception as error:
            print(f"YouTube source search skipped for {provider}: {error}")
    return all_results


def _download(url, path):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ViralVideoAutomationBot/1.0)", "Accept": "*/*"}
    last_error = None
    for attempt in range(5):
        try:
            with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, headers=headers) as response:
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        wait = min(30, max(2, int(retry_after)))
                    except ValueError:
                        wait = min(30, 2 ** attempt)
                    print(f"YouTube source rate-limited (429); retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                with open(path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            return path
        except requests.RequestException as error:
            last_error = error
            if attempt < 4:
                time.sleep(min(20, 2 ** attempt))
            else:
                raise
    raise last_error


def _probe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


TITLE_SECONDS = max(1.2, float(os.getenv("YOUTUBE_TITLE_SECONDS", "1.5")))


def _drawtext_filter(text, fontsize, y, box=False):
    safe = str(text).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    box_part = ":box=1:boxcolor=black@0.62:boxborderw=18" if box else ""
    return (
        f"drawtext=text='{safe}':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"fontsize={fontsize}:fontcolor=white:x=(w-text_w)/2:y={y}{box_part}"
    )


def _make_clip(source, destination, start, duration, rank=None):
    filters = [
        "scale=1080:1920:force_original_aspect_ratio=increase",
        "crop=1080:1920",
        "eq=contrast=1.04:saturation=1.06:brightness=0.01",
    ]
    if rank is not None:
        filters.append(_drawtext_filter(f"#{rank}", 86, "h*0.08", box=True))
        filters.append(_drawtext_filter("TOP 10", 30, "h*0.14", box=False))
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(start), "-i", str(source),
        "-t", str(duration),
        "-vf", ",".join(filters),
        "-r", "30", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-movflags", "+faststart", str(destination)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _make_title_card(title, destination):
    filters = [
        "format=yuv420p",
        _drawtext_filter(title.upper(), 78, "h*0.34", box=True),
        _drawtext_filter("#10  ->  #1", 48, "h*0.53", box=False),
        _drawtext_filter("WATCH UNTIL #1", 34, "h*0.61", box=False),
        "fade=t=in:st=0:d=0.12",
        f"fade=t=out:st={max(0.1, TITLE_SECONDS-0.14):.3f}:d=0.14",
    ]
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=1080x1920:r=30",
        "-t", f"{TITLE_SECONDS:.3f}",
        "-vf", ",".join(filters),
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-movflags", "+faststart", str(destination)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _normalize_audio(path):
    subprocess.run([
        "ffmpeg", "-y", "-i", str(path),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", "48000", "-c:a", "aac", "-b:a", "128k",
        str(path.with_name(path.stem + "_norm.m4a"))
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path.with_name(path.stem + "_norm.m4a")


def _concat(clips, output):
    if len(clips) == 1:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(clips[0]), "-c", "copy", "-movflags", "+faststart", str(output)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output

    inputs = []
    filters = []
    for i, clip in enumerate(clips):
        inputs += ["-i", str(clip)]
        filters.append(f"[{i}:v]settb=AVTB,setsar=1[v{i}]")

    current = "v0"
    offset = CLIP_SECONDS - 0.25
    for i in range(1, len(clips)):
        out = f"x{i}"
        filters.append(f"[{current}][v{i}]xfade=transition=fade:duration=0.25:offset={offset:.2f}[{out}]")
        current = out
        offset += CLIP_SECONDS - 0.25

    subprocess.run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", f"[{current}]",
        "-an", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output


def _listicle_theme(trend):
    text = str(trend).lower()
    if any(w in text for w in ("horror", "scary", "creepy", "terrifying", "ghost", "haunted", "spooky")):
        return "scariest"
    if any(w in text for w in ("funny", "funniest", "comedy", "laugh", "fail", "fails", "hilarious")):
        return "funniest"
    if any(w in text for w in ("crazy", "wild", "unexpected", "insane", "shocking")):
        return "wildest"
    return "most interesting"


def _short_detail(source):
    text = re.sub(r"\\s+", " ", source.get("description", "") or "").strip()
    if not text:
        text = re.sub(r"\\s+", " ", source.get("title", "") or "").strip()
    words = re.findall(r"[A-Za-z0-9']+", text)
    return " ".join(words[:7])


def _listicle_commentary(rank, opportunity, source):
    trend = opportunity.get("trend", "this topic")
    theme = _listicle_theme(trend)
    detail = _short_detail(source)
    if rank == 1:
        return f"Top 10 {theme} real-life moments. Starting at number 10."
    if detail:
        return f"Number {11-rank}. {detail}."
    return f"Number {11-rank}. Watch this one closely."


def _source_score(source, query):
    text = " ".join([
        str(source.get("title", "")),
        str(source.get("description", "")),
        str(query),
    ]).lower()
    keyword_map = {
        "funniest": ("funny", "funniest", "laugh", "hilarious", "fail", "fails", "comedy"),
        "scariest": ("scary", "horror", "creepy", "ghost", "haunted", "terrifying"),
        "wildest": ("wild", "crazy", "unexpected", "insane", "shocking"),
    }
    theme = _listicle_theme(query)
    score = sum(3 for word in keyword_map.get(theme, ()) if word in text)
    if source.get("provider") == "Pexels":
        score += 3
    elif source.get("provider") == "Pixabay":
        score += 2
    elif source.get("provider") == "Wikimedia Commons":
        score += 1
    if source.get("creator"):
        score += 1
    return score


def _tts(text, path):
    """Generate narration with ElevenLabs first, then fall back to edge-tts.

    ElevenLabs is optional. If its key is missing, rate-limited, unavailable,
    or returns an invalid response, the free/local edge-tts path is used.
    """
    if TTS_ENGINE in {"none", "text"}:
        return None

    if ELEVENLABS_ENABLED and ELEVENLABS_API_KEY:
        try:
            endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
            response = requests.post(
                endpoint,
                params={"output_format": "mp3_44100_128"},
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": ELEVENLABS_MODEL,
                },
                timeout=120,
            )
            response.raise_for_status()
            if not response.content.startswith(b"ID3") and not response.content.startswith(b"\xff\xfb"):
                raise ValueError("ElevenLabs returned unexpected audio data")
            path.write_bytes(response.content)
            print("YouTube TTS: ElevenLabs voice generated successfully.")
            return str(path)
        except Exception as error:
            print(f"YouTube TTS: ElevenLabs failed; falling back to edge-tts: {error}")

    try:
        if TTS_ENGINE in {"auto", "edge"}:
            import asyncio
            import edge_tts
            async def make():
                await edge_tts.Communicate(text, TTS_VOICE).save(str(path))
            asyncio.run(make())
            print("YouTube TTS: edge-tts fallback generated successfully.")
            return str(path)
    except Exception as error:
        print(f"YouTube TTS fallback failed: {error}")
    return None


def create_youtube_commentary_video(opportunity, index):
    root = Path(OUTPUT_DIR) / f"youtube_{index}"
    root.mkdir(parents=True, exist_ok=True)
    query = opportunity.get("trend") or "interesting real life moments"
    theme = _listicle_theme(query)
    search_limit = max(CLIPS_PER_VIDEO * 4, 30)
    if theme == "funniest":
        queries = [f"{query} funny people", "funny people caught on camera", "funny real life moments", "funny fails"]
    elif theme == "scariest":
        queries = [f"{query} scary real life", "scary people caught on camera", "creepy real life moments", "scary public domain video"]
    elif theme == "wildest":
        queries = [f"{query} wild real life", "unexpected moments caught on camera", "crazy real life moments", "crazy public domain video"]
    else:
        queries = [query, f"{query} real life", "interesting real life moments", "people real life"]
    sources, seen = [], set()
    for search_query in queries:
        try:
            candidates = _search_sources(search_query, limit=search_limit)
        except Exception as error:
            print(f"YouTube source search failed for '{search_query}': {error}")
            continue
        for item in candidates:
            key = item.get("source_url") or item.get("url")
            if not key or key in seen:
                continue
            seen.add(key)
            item["_match_score"] = _source_score(item, query)
            sources.append(item)
        if len(sources) >= CLIPS_PER_VIDEO * 4:
            break

    sources.sort(key=lambda item: item.get("_match_score", 0), reverse=True)
    ordered_sources = []
    remaining = list(sources)
    last_provider = None
    while remaining and len(ordered_sources) < min(len(sources), CLIPS_PER_VIDEO * 3):
        pool = [x for x in remaining if x.get("provider") != last_provider] or remaining
        chosen = pool[0]
        ordered_sources.append(chosen)
        remaining.remove(chosen)
        last_provider = chosen.get("provider")
    sources = ordered_sources

    clips, manifest = [], []
    for clip_index, source in enumerate(sources):
        if len(clips) >= CLIPS_PER_VIDEO:
            break
        raw = root / f"source_{clip_index}_{_safe_name(source['title'])}.mp4"
        segment = root / f"segment_{clip_index}.mp4"
        try:
            _download(source["url"], raw)
            duration = _probe_duration(raw)
            if duration < CLIP_SECONDS + 0.5:
                continue
            max_start = max(0.0, duration - CLIP_SECONDS)
            starts = [0.12 * duration, 0.35 * duration, 0.55 * duration, 0.75 * duration]
            start = min(starts[clip_index % len(starts)], max_start)
            rank = CLIPS_PER_VIDEO - len(clips)
            _make_clip(raw, segment, start, CLIP_SECONDS, rank=rank)
            clips.append(segment)
            clean_source = dict(source)
            clean_source.pop("_match_score", None)
            manifest.append(clean_source)
        except (requests.RequestException, subprocess.CalledProcessError, ValueError, OSError) as error:
            print(f"YouTube clip skipped: {source.get('title','unknown')} ({source.get('provider','unknown')}): {error}")
            continue

    if len(clips) < CLIPS_PER_VIDEO:
        raise RuntimeError(f"YouTube video #{index} produced only {len(clips)} usable clips; need {CLIPS_PER_VIDEO}")

    title_card = root / "title_card.mp4"
    if theme == "funniest":
        title_text = "TOP 10 FUNNIEST MOMENTS"
    elif theme == "scariest":
        title_text = "TOP 10 SCARIEST MOMENTS"
    elif theme == "wildest":
        title_text = "TOP 10 WILDEST MOMENTS"
    else:
        title_text = "TOP 10 MOMENTS"
    _make_title_card(title_text, title_card)

    combined_clips = [title_card] + clips
    combined = root / "combined.mp4"

    # Concatenate decoded video streams with FFmpeg's concat filter.
    # The concat demuxer can reject otherwise valid MP4 segments when their
    # timestamps/time bases differ. Each segment is decoded, reset to a common
    # 30-fps timeline, then concatenated and encoded once.
    inputs = []
    filter_parts = []
    for i, item in enumerate(combined_clips):
        inputs += ["-i", str(item)]
        filter_parts.append(
            f"[{i}:v:0]fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,settb=1/30,format=yuv420p[v{i}]"
        )
    concat_inputs = "".join(f"[v{i}]" for i in range(len(combined_clips)))
    filter_parts.append(
        f"{concat_inputs}concat=n={len(combined_clips)}:v=1:a=0,settb=1/30,"
        "format=yuv420p[vout]"
    )
    subprocess.run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]",
        "-an", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(combined)
    ], check=True)

    comments = [_listicle_commentary(rank, opportunity, source) for rank, source in enumerate(manifest, 1)]
    full_commentary = " ".join(comments)
    audio = root / "commentary.mp3"
    audio_path = _tts(full_commentary, audio)

    final = Path(OUTPUT_DIR) / f"youtube_commentary_{index}.mp4"
    if audio_path and YOUTUBE_MODE != "text":
        subprocess.run([
            "ffmpeg", "-y", "-i", str(combined), "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "48000", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart", str(final)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        mode = "ai_voice"
    else:
        subtitle = root / "commentary.srt"
        cursor = 0
        lines = []
        cursor = TITLE_SECONDS
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
        "platform": "youtube", "mode": mode, "format": "top_10_listicle",
        "trend": opportunity.get("trend", ""), "commentary": comments,
        "editing": {
            "clips": CLIPS_PER_VIDEO,
            "clip_seconds": CLIP_SECONDS,
            "title_card_seconds": TITLE_SECONDS,
            "countdown": "#10 -> #1",
            "crossfade_seconds": 0.10,
            "audio_normalization": True,
            "aspect_ratio": "9:16",
            "burned_in_text": True,
            "title_card": title_text,
            "rank_overlay": True,
        },
        "sources": manifest,
        "license_policy": (
            "Automated sources are limited to Wikimedia Commons items with license metadata, "
            "Pexels, Pixabay, and Internet Archive items whose metadata identifies a Creative Commons/public-domain license. "
            "Mixkit is not automated because its current terms prohibit scripts/bots from mass-downloading items."
        ),
    }
    meta_path = Path(OUTPUT_DIR) / f"youtube_commentary_{index}.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(final), str(meta_path)
