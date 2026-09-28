import base64
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import requests

from config import (OUTPUT_DIR, TTS_ENGINE, TTS_VOICE, ELEVENLABS_ENABLED, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID_1, ELEVENLABS_VOICE_ID_2, ELEVENLABS_MODEL, ELEVENLABS_TEST_VOICES)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
PEXELS_API = "https://api.pexels.com/v1/videos/search"
PIXABAY_API = "https://pixabay.com/api/videos/"
IA_ADVANCEDSEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/{identifier}"

YOUTUBE_MODE = os.getenv("YOUTUBE_COMMENTARY_MODE", "voice").lower()
CLIPS_PER_VIDEO = min(10, max(5, int(os.getenv("YOUTUBE_CLIPS_PER_VIDEO", "10"))))
# Tight clips keep the countdown moving and leave room for a genuinely fast voice.
CLIP_SECONDS = max(2.5, float(os.getenv("YOUTUBE_CLIP_SECONDS", "3.0")))
# Final ranking uses actual visual evidence, not discovery order.
FINAL_RANK_VISUAL_WEIGHT = max(0.0, min(1.0, float(os.getenv("YOUTUBE_FINAL_RANK_VISUAL_WEIGHT", "0.70"))))
FINAL_RANK_LOCAL_WEIGHT = 1.0 - FINAL_RANK_VISUAL_WEIGHT
DOWNLOAD_TIMEOUT = int(os.getenv("YOUTUBE_CLIP_TIMEOUT", "8"))
DOWNLOAD_TOTAL_TIMEOUT = int(os.getenv("YOUTUBE_DOWNLOAD_TOTAL_TIMEOUT", "15"))
MAX_DOWNLOAD_BYTES = int(os.getenv("YOUTUBE_MAX_DOWNLOAD_BYTES", "80000000"))
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
IA_ENABLED = os.getenv("INTERNET_ARCHIVE_ENABLED", "true").lower() == "true"
YOUTUBE_AI_SELECTOR_ENABLED = os.getenv("YOUTUBE_AI_SELECTOR_ENABLED", "true").lower() == "true"
AI_SELECTOR_CANDIDATES = max(12, int(os.getenv("YOUTUBE_AI_SELECTOR_CANDIDATES", "24")))
VISUAL_QC_LIMIT = max(CLIPS_PER_VIDEO * 6, int(os.getenv("YOUTUBE_VISUAL_QC_LIMIT", "80")))
GEMINI_VISUAL_QC_LIMIT = max(0, int(os.getenv("YOUTUBE_GEMINI_VISUAL_QC_LIMIT", "18")))
REAL_FOOTAGE_BAD_TERMS = (
    "animation", "animated", "cartoon", "illustration", "illustrated", "3d render",
    "cgi", "computer generated", "graphic", "diagram", "infographic", "wallpaper",
    "background", "blender", "dna", "skeleton", "logo", "abstract", "particles",
    "bokeh", "screen recording", "slideshow", "still image", "photo montage",
)
SOURCE_HISTORY_LIMIT = max(20, int(os.getenv("YOUTUBE_SOURCE_HISTORY_LIMIT", "120")))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
ELEVENLABS_ENABLED = os.getenv("ELEVENLABS_ENABLED", "false").lower() == "true"
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb").strip()
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5").strip()


def _safe_name(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return value[:80] or "clip"


def _clean(value):
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


YOUTUBE_UNRELATED_TERMS = (
    "marine","marines","military","soldier","soldiers","army","navy","war","warfare",
    "battlefield","battle","weapon","weapons","gun","politics","political","election",
    "president","parliament","news","documentary","history","historical","interview",
    "lecture","tutorial","weather","wildlife","safari","zoo","nature documentary",
)
def _youtube_topic_is_unrelated(text, theme):
    if theme not in {"funniest","scariest","wildest"}: return False
    normalized=re.sub(r"[^a-z0-9 ]+"," ",str(text).lower())
    return any(re.search(rf"\b{re.escape(term)}\b",normalized) for term in YOUTUBE_UNRELATED_TERMS)

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
        preferred = [x for x in files if 640 <= (x.get("width") or 0) <= 1280]
        chosen = max(preferred or files, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
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
        headers={"User-Agent": "ViralVideoAutomationBot/1.0"}, timeout=30,
    )
    response.raise_for_status()
    results = []
    for item in response.json().get("hits", []):
        videos = item.get("videos", {})
        candidates = [v for v in videos.values() if isinstance(v, dict) and v.get("url")]
        candidates.sort(key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True)
        if not candidates:
            continue
        preferred = [x for x in candidates if 640 <= (x.get("width") or 0) <= 1280]
        chosen = max(preferred or candidates, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
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
            "mime": "video/mp4", "license": doc.get("licenseurl", ""),
            "description": _clean(doc.get("description", "")),
            "source_url": f"https://archive.org/details/{quote(identifier)}",
            "provider": "Internet Archive",
        })
    return results


def _search_sources(query, limit):
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
    for attempt in range(2):
        try:
            started = time.monotonic()
            with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, headers=headers) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit() and int(content_length) > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"source too large: {int(content_length) / 1_000_000:.1f} MB")
                if response.status_code == 429:
                    # Treat rate limiting as a normal candidate rejection.
                    # The caller already catches RequestException and moves on.
                    raise requests.HTTPError("source rate-limited (429)")
                response.raise_for_status()
                with open(path, "wb") as handle:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if time.monotonic() - started > DOWNLOAD_TOTAL_TIMEOUT:
                            raise TimeoutError("source download exceeded total time limit")
                        if chunk:
                            downloaded += len(chunk)
                            if downloaded > MAX_DOWNLOAD_BYTES:
                                raise ValueError("source exceeded download size limit")
                            handle.write(chunk)
            return path
        except requests.RequestException as error:
            last_error = error
            if attempt < 1:
                time.sleep(2)
            else:
                raise
    raise last_error or RuntimeError("source download failed after retries")


def _probe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


# Do not waste the first seconds on a black title card. The first real clip is the hook.
TITLE_SECONDS = max(0.0, float(os.getenv("YOUTUBE_TITLE_SECONDS", "0.0")))


def _drawtext_filter(text, fontsize, y, box=False):
    safe = str(text).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    box_part = ":box=1:boxcolor=black@0.62:boxborderw=18" if box else ""
    return (
        f"drawtext=text='{safe}':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"fontsize={fontsize}:fontcolor=white:x=(w-text_w)/2:y={y}{box_part}"
    )


def _make_clip(source, destination, start, duration, rank=None):
    """Create a Shorts-style vertical clip without destroying the source composition.

    Landscape footage is kept intact in the center with a blurred, darkened copy
    filling the 9:16 canvas. This fixes the old aggressive crop that often cut the
    actual subject out of frame.
    """
    rank_text = ""
    if rank is not None:
        rank_text = "," + _drawtext_filter(f"#{rank}", 70, "h*0.055", box=True)
    filter_graph = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=18:8,eq=brightness=-0.28:saturation=0.82[bg2];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease,"
        "eq=contrast=1.05:saturation=1.06:brightness=0.01[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2{rank_text},format=yuv420p[out]"
    )
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(start), "-i", str(source),
        "-t", str(duration), "-filter_complex", filter_graph,
        "-map", "[out]", "-r", "30", "-an", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-preset", "veryfast", "-movflags", "+faststart",
        str(destination)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


def _make_title_card(title, destination):
    # Kept for compatibility with older callers; the production listicle no longer
    # inserts a black intro because the first real clip is the hook.
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=1080x1920:r=30",
        "-t", "0.05", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(destination)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def _short_detail(source):
    text = re.sub(r"\s+", " ", source.get("description", "") or "").strip()
    if not text:
        text = re.sub(r"\s+", " ", source.get("title", "") or "").strip()
    words = re.findall(r"[A-Za-z0-9']+", text)
    return " ".join(words[:6])


def _listicle_theme(trend):
    if isinstance(trend, dict):
        explicit = str(trend.get("listicle_theme", "")).lower().strip()
        if explicit in {"funniest", "scariest", "wildest"}:
            return explicit
        trend = trend.get("trend", "")
    text = str(trend).lower()
    if any(w in text for w in ("horror", "scary", "creepy", "terrifying", "ghost", "haunted", "spooky")):
        return "scariest"
    if any(w in text for w in ("funny", "funniest", "comedy", "laugh", "fail", "fails", "hilarious")):
        return "funniest"
    if any(w in text for w in ("crazy", "wild", "unexpected", "insane", "shocking")):
        return "wildest"
    return "most interesting"


def _source_score(source, query):
    """Semantic-ish source ranking with hard relevance gates.

    This is intentionally deterministic/free: it uses the actual source metadata,
    theme-specific positive signals, and strong negative signals. Generic wildlife,
    landscapes, portraits and calm stock footage should not beat an actual event.
    """
    title = str(source.get("title", "")).lower()
    description = str(source.get("description", "")).lower()
    text = f"{title} {description}"
    theme = _listicle_theme(query)

    positives = {
        "funniest": (
            "funny", "funniest", "laugh", "hilarious", "comedy", "humor",
            "prank", "fail", "fails", "reaction", "surprise", "awkward",
            "silly", "crazy", "mistake", "fall", "unexpected",
        ),
        "scariest": (
            "scary", "horror", "creepy", "ghost", "haunted", "terrifying",
            "fear", "frightened", "dark", "spooky", "eerie", "paranormal",
            "chase", "scream", "night", "strange", "unexplained",
        ),
        "wildest": (
            "wild", "crazy", "unexpected", "insane", "shocking", "chaos",
            "extreme", "surprise", "accident", "near miss", "stunt",
            "crash", "speed", "collision", "dramatic", "reaction",
        ),
    }
    negatives = {
        "funniest": (
            "tiger", "lion", "elephant", "giraffe", "zoo", "wildlife",
            "safari", "nature", "landscape", "mountain", "sunset", "ocean",
            "forest", "flower", "portrait", "fashion", "model", "cat", "dog",
        ),
        "scariest": (
            "tiger", "lion", "zoo", "wildlife", "safari", "landscape",
            "sunset", "flower", "fashion", "model", "portrait",
        ),
        "wildest": (
            "sunset", "landscape", "flower", "portrait", "fashion", "model",
            "calm", "peaceful", "meditation", "ocean", "sea", "nature",
            "wildlife", "safari", "zoo", "animal", "animals", "tree", "forest",
            "grass", "field", "garden", "sky", "cloud", "clouds", "mountain",
            "astronomy", "galaxy", "cosmos", "comet", "asteroid", "planet",
            "earth", "space", "stars", "starry", "milky way", "underwater",
            "fish", "whale", "bird", "birds",
        ),
    }
    event_words = (
        "people", "person", "reaction", "caught", "moment", "camera", "crowd",
        "street", "public", "fail", "accident", "surprise", "unexpected",
        "chase", "fall", "crash", "prank", "scream", "stunt",
    )

    positive_hits = sum(1 for word in positives.get(theme, ()) if word in text)
    negative_hits = sum(1 for word in negatives.get(theme, ()) if word in text)
    event_hits = sum(1 for word in event_words if word in text)

    # Search-engine relevance is an important signal for stock providers such as
    # Pexels, whose API metadata often contains only a URL and creator name.
    search_text = str(source.get("_search_query", "")).lower()
    search_hits = sum(1 for word in positives.get(theme, ()) if word in search_text)
    query_event_hits = sum(1 for word in event_words if word in search_text)
    score = positive_hits * 12 + event_hits * 3 - negative_hits * 24
    score += min(3, search_hits) * 5 + min(2, query_event_hits) * 2

    generic_terms = (
        "nature", "landscape", "ocean", "sea", "forest", "flower", "garden",
        "mountain", "sunset", "sunrise", "astronomy", "galaxy", "cosmos",
        "comet", "asteroid", "planet", "earth", "space", "milky way",
        "wildlife", "safari", "zoo", "portrait", "fashion", "model",
        "meditation", "peaceful", "calm", "underwater",
    )
    concrete_event_terms = (
        "people", "person", "man", "woman", "crowd", "reaction", "caught",
        "camera", "street", "public", "fail", "accident", "surprise",
        "chase", "fall", "crash", "prank", "scream", "stunt", "motorcycle",
        "motorbike", "motocross", "skateboard", "skate", "bicycle", "bike",
        "car", "race", "racing", "collision", "jump", "driver", "rider",
        "sport", "sports", "extreme",
    )
    generic_hits = sum(1 for word in generic_terms if word in text)
    concrete_hits = sum(1 for word in concrete_event_terms if word in text)
    synthetic_hits = sum(1 for word in REAL_FOOTAGE_BAD_TERMS if word in text)
    if synthetic_hits:
        score -= 80 * min(2, synthetic_hits)
    if generic_hits >= 2:
        score -= 35
    elif generic_hits == 1 and concrete_hits == 0:
        score -= 25
    if theme == "wildest" and concrete_hits == 0:
        score -= 30
    if source.get("provider") in {"Pexels", "Pixabay"} and search_hits >= 1:
        score += 8

    # A funny list needs evidence of a funny/event-like situation.
    # Generic wildlife/landscape clips are now pushed far below the threshold.
    if theme in {"funniest", "scariest"} and positive_hits == 0:
        if event_hits > 0 and search_hits > 0:
            score -= 8
        else:
            score -= 30
    if theme == "funniest" and event_hits == 0 and query_event_hits == 0:
        score -= 20
    elif theme == "funniest" and (event_hits > 0 or query_event_hits > 0) and search_hits > 0:
        score += 10
    if theme == "scariest" and not any(w in text for w in ("scary", "horror", "creepy", "ghost", "haunted", "eerie", "paranormal", "scream", "fright")):
        score -= 25
    if theme == "wildest" and positive_hits == 0:
        score -= 20

    provider = source.get("provider")
    if provider == "Wikimedia Commons":
        score += 2
    elif provider in {"Pexels", "Pixabay"}:
        score += 1
    if source.get("creator"):
        score += 1
    return score



def _strict_source_gate(source, theme):
    """Hard semantic gate: never fill a listicle with merely keyword-adjacent stock.

    Run 406 exposed the weakness of scoring search-query words as if they were
    evidence in the actual footage metadata. A search for 'scary people' could
    therefore admit beaches, city tours, or cameras. These rules require the
    source itself to contain a concrete theme signal.
    """
    text = f"{source.get('title','')} {source.get('description','')}".lower()

    generic_banned = (
        "landscape", "sunset", "sunrise", "vacation", "holiday", "tourism",
        "tourist", "beach", "ocean", "sea", "forest path", "garden",
        "astronomy", "galaxy", "cosmos", "comet", "asteroid", "milky way",
        "planet", "earth", "space", "nature", "wildlife", "safari",
        "zoo", "flower", "underwater", "portrait", "fashion", "model",
        "meditation", "peaceful", "calm", "live wallpaper", "drone",
    )
    if any(term in text for term in REAL_FOOTAGE_BAD_TERMS):
        return False

    if any(term in text for term in generic_banned):
        # Scary footage can legitimately be dark/night footage, but generic
        # travel/nature/astronomy footage is never a substitute for the promised event.
        if theme != "scariest" or any(term in text for term in (
            "beach", "vacation", "holiday", "tourism", "tourist", "nature",
            "wildlife", "safari", "zoo", "landscape", "sunset", "sunrise",
            "live wallpaper", "drone"
        )):
            return False

    event_terms = (
        "people", "person", "man", "woman", "crowd", "reaction", "caught",
        "camera", "street", "public", "fail", "accident", "surprise",
        "chase", "fall", "crash", "prank", "scream", "stunt", "jump",
        "rider", "racing", "race", "collision", "skateboard", "motorcycle",
        "motorbike", "bike", "driver",
    )

    action_event_terms = ("fail", "accident", "surprise", "chase", "fall", "crash", "prank", "scream", "stunt", "jump", "collision", "racing", "race", "skateboard", "motorcycle", "motorbike", "bike", "instant regret", "mishap", "mistake", "reaction", "awkward", "performance", "sports", "sport", "crowd", "street", "caught", "camera", "public")

    required = {
        "funniest": (
            "funny", "funniest", "hilarious", "comedy", "humor", "prank",
            "fail", "fails", "bloopers", "awkward", "silly", "laugh",
        ),
        "scariest": (
            "scary", "horror", "creepy", "ghost", "haunted", "terrifying",
            "fright", "fear", "scream", "eerie", "paranormal", "nightmare",
            "terror", "unexplained",
        ),
        "wildest": (
            "wild", "crazy", "insane", "shocking", "extreme", "accident",
            "near miss", "stunt", "crash", "collision", "speed", "jump",
            "chaos", "dramatic",
        ),
    }
    hits = [term for term in required.get(theme, ()) if term in text]
    event_hits = sum(1 for term in event_terms if term in text)
    action_hits = sum(1 for term in action_event_terms if term in text)

    search_text = str(source.get("_search_query", "")).lower()
    search_event_hits = sum(1 for term in event_terms if term in search_text)
    search_action_hits = sum(1 for term in action_event_terms if term in search_text)
    search_theme_hits = sum(1 for term in required.get(theme, ()) if term in search_text)

    if theme in {"funniest", "scariest", "wildest"} and not hits:
        if not (search_theme_hits > 0 and (action_hits > 0 or event_hits >= 2 or search_action_hits > 0 or search_event_hits >= 2)):
            return False
    if theme == "funniest":
        animal_stock = (
            "animal", "animals", "cat", "kitten", "dog", "puppy", "monkey",
            "chimp", "chimpanzee", "penguin", "turtle", "bird", "fish",
            "lion", "tiger", "elephant", "wildlife", "zoo", "safari",
        )
        if any(term in text for term in animal_stock):
            return False
        # Stock providers often return weak metadata. If the search is explicitly funny/action-based,
        # let the downloaded clip reach visual QC instead of rejecting it here.
        if action_hits == 0 and not (search_theme_hits > 0 and (search_action_hits > 0 or search_event_hits > 0)):
            return False
        comedy_evidence = (
            "funny", "funniest", "hilarious", "comedy", "humor", "humour",
            "prank", "fail", "fails", "bloopers", "awkward", "silly",
            "laugh", "mistake", "mishap", "instant regret",
        )
        if not any(term in text for term in comedy_evidence):
            if not (search_theme_hits > 0 and (search_event_hits > 0 or search_action_hits > 0)):
                return False
    if theme == "wildest" and event_hits == 0 and not (search_theme_hits > 0 and (search_event_hits > 0 or search_action_hits > 0)):
        return False
    return True


def _gemini_rank_sources(sources, theme):
    """Optional AI judge for source metadata; falls back safely on errors."""
    if not YOUTUBE_AI_SELECTOR_ENABLED or not GEMINI_API_KEY or not sources or os.getenv("GEMINI_ENABLED", "true").lower() != "true":
        return sources
    sources = sources[:AI_SELECTOR_CANDIDATES]
    candidates = [{"id": i, "title": str(s.get("title", ""))[:180],
                   "description": str(s.get("description", ""))[:300],
                   "provider": s.get("provider", "")} for i, s in enumerate(sources[:36])]
    prompt = (
        f"You are a strict casting editor for a viral YouTube Top-10 {theme} listicle. "
        "Score candidates only from metadata. Prefer footage clearly matching the promised event "
        "and likely to work in a 3.0-second vertical clip. Reject generic landscapes, wildlife, "
        "portraits, calm stock footage, and unrelated clips. Return ONLY JSON like "
        "[{\"id\":0,\"score\":0,\"reason\":\"short\"}]. "
        f"Candidates: {json.dumps(candidates, ensure_ascii=False)}"
    )
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2500}},
            timeout=45,
        )
        response.raise_for_status()
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise ValueError("Gemini returned no JSON ranking")
        judged = json.loads(match.group(0))
        by_id = {int(x["id"]): x for x in judged if isinstance(x, dict) and str(x.get("id", "")).isdigit()}
        for i, source in enumerate(sources):
            if i in by_id:
                ai_score = max(0, min(100, int(by_id[i].get("score", 0))))
                source["_ai_score"] = ai_score
                source["_ai_reason"] = str(by_id[i].get("reason", ""))[:180]
                local_score = source.get("_match_score", 0)
                source["_match_score"] = local_score * 0.25 + ai_score * 0.75
        print(f"YouTube AI selector: Gemini judged {len(by_id)} candidates for {theme}.")
    except Exception as error:
        print(f"YouTube AI selector unavailable; using local selector: {error}")
    return sources




def _gemini_post(payload, timeout=30, attempts=4):
    """Call Gemini with bounded backoff for transient 429/5xx responses."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                url,
                headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(12, 2 ** attempt)
                except ValueError:
                    delay = min(12, 2 ** attempt)
                print(f"Gemini transient HTTP {response.status_code}; retrying in {delay:.1f}s.")
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt + 1 < attempts:
                delay = min(12, 2 ** attempt)
                print(f"Gemini request error; retrying in {delay}s: {error}")
                time.sleep(delay)
    if last_error:
        raise last_error
    raise RuntimeError("Gemini request failed after retries")


def _gemini_expand_search_queries(theme, shard_index):
    """Ask Gemini for fresh, concrete search queries so research does not stagnate."""
    if (
        not YOUTUBE_AI_SELECTOR_ENABLED
        or not GEMINI_API_KEY
        or os.getenv("GEMINI_ENABLED", "true").lower() != "true"
    ):
        return []
    prompt = (
        f"Create 10 fresh search-engine queries for a YouTube Top-10 {theme} listicle. "
        "The ONLY subject is short real human-action moments matching the theme. "
        "For funniest: harmless human fails, awkward moments, instant regrets, funny reactions, "
        "sports/public mishaps and perfect timing. Never search for stories, documentaries, news, "
        "military/marines/war, history, politics, animals, scenery, or generic subjects. "
        "Every query must contain a strong theme signal such as funny, fail, reaction, hilarious, "
        "scary, creepy, wild, crazy, shocking, caught on camera, or instant regret. "
        "Return ONLY a JSON array of 10 short search queries. Do not number them."
    )
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.9, "maxOutputTokens": 500}},
            timeout=25,
        )
        response.raise_for_status()
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise ValueError("Gemini search planner returned no JSON")
        queries = json.loads(match.group(0))
        cleaned = []
        for query in queries:
            query = re.sub(r"\s+", " ", str(query)).strip()
            if 12 <= len(query) <= 120:
                lower=query.lower()
                signals={"funniest":("funny","fail","fails","hilarious","reaction","awkward","instant regret"),
                         "scariest":("scary","creepy","horror","ghost","haunted","scream"),
                         "wildest":("wild","crazy","insane","shocking","extreme","near miss","stunt","crash")}.get(theme,())
                if any(x in lower for x in signals) and not _youtube_topic_is_unrelated(lower,theme):
                    cleaned.append(query)
        print(f"YouTube AI research planner: generated {len(cleaned)} fresh queries for shard {shard_index}.")
        return list(dict.fromkeys(cleaned))[:10]
    except Exception as error:
        print(f"YouTube AI research planner unavailable; using built-in query bank: {error}")
        return []


def _load_source_history():
    path = Path(os.getenv("YOUTUBE_SOURCE_HISTORY_FILE", "youtube_source_history.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(str(x) for x in data if x)
    except Exception:
        return set()


def _save_source_history(keys):
    path = Path(os.getenv("YOUTUBE_SOURCE_HISTORY_FILE", "youtube_source_history.json"))
    try:
        existing = []
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing = [str(x) for x in data if x]
        merged = list(dict.fromkeys(existing + [str(x) for x in keys if x]))
        path.write_text(json.dumps(merged[-SOURCE_HISTORY_LIMIT:], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as error:
        print(f"YouTube source history could not be saved: {error}")


def _gemini_visual_judge(path, theme, source, clip_start=0.0):
    """Judge several real frames from the downloaded clip, not just metadata."""
    if (
        not YOUTUBE_AI_SELECTOR_ENABLED
        or not GEMINI_API_KEY
        or os.getenv("GEMINI_ENABLED", "true").lower() != "true"
    ):
        return True, 50, "visual AI disabled; local QC only"

    sample_dir = Path(path).with_suffix(".ai_frames")
    frames = []
    try:
        duration = _probe_duration(path)
        clip_end = min(duration, float(clip_start) + CLIP_SECONDS)
        window = max(0.2, clip_end - float(clip_start))
        for idx, pct in enumerate((0.18, 0.52, 0.86)):
            frame = sample_dir / f"frame_{idx}.jpg"
            sample_dir.mkdir(exist_ok=True)
            midpoint = max(0.1, min(duration - 0.1, float(clip_start) + window * pct))
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error", "-ss", str(midpoint),
                "-i", str(path), "-frames:v", "1",
                "-vf", "scale=512:-1:force_original_aspect_ratio=decrease",
                "-q:v", "5", str(frame)
            ], check=True, timeout=8)
            frames.append(frame)

        parts = [{
            "text": (
                f"You are the strict final casting judge for a YouTube Top-10 {theme} Short. "
                "Judge ONLY what is visibly happening in these three frames from the SAME clip. "
                "This must be real human-action footage, not animation, CGI, illustrations, diagrams, "
                "wallpapers, generic stock scenery, posed portraits, or unrelated footage. "
                "For FUNNY clips, require a visible human fail, awkward moment, reaction, mishap, "
                "surprise, prank, or obvious comedic timing. A person merely walking, smiling, dancing "
                "normally, posing, sightseeing, or looking at something is NOT enough. "
                "For SCARY clips, require a visibly scary/creepy human situation or reaction. "
                "For WILDEST clips, require a visibly unusual, high-energy, risky, shocking, or chaotic event. "
                "Reject clips where the promised moment is not actually visible. "
                "Return ONLY JSON: {\"relevant\":true/false,\"score\":0-100,"
                "\"visible_action\":\"short concrete description\","
                "\"hook\":\"short reason viewers would keep watching\","
                "\"reason\":\"short rejection/approval reason\"}."
            )
        }];
        for frame in frames:
            parts.push({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(frame.read_bytes()).decode("ascii"),
                }
            })

        response = _gemini_post(
            {"contents": [{"parts": parts}],
             "generationConfig": {
                 "temperature": 0.0,
                 "maxOutputTokens": 220,
                 "response_mime_type": "application/json",
                 "response_schema": {
                     "type": "object",
                     "properties": {
                         "relevant": {"type": "boolean"},
                         "score": {"type": "integer"},
                         "visible_action": {"type": "string"},
                         "hook": {"type": "string"},
                         "reason": {"type": "string"},
                     },
                     "required": ["relevant", "score", "visible_action", "hook", "reason"],
                 },
             }},
            timeout=35,
        )
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise ValueError("Gemini visual judge returned no JSON")
        verdict = json.loads(match.group(0))
        score = max(0, min(100, int(verdict.get("score", 0))))
        relevant = bool(verdict.get("relevant", False))
        action = re.sub(r"\s+", " ", str(verdict.get("visible_action", ""))).strip()[:220]
        hook = re.sub(r"\s+", " ", str(verdict.get("hook", ""))).strip()[:180]
        reason = re.sub(r"\s+", " ", str(verdict.get("reason", ""))).strip()[:180]
        source["_visual_ai_score"] = score
        source["_visual_ai_reason"] = reason
        source["_visual_ai_action"] = action
        source["_visual_ai_hook"] = hook
        return relevant and score >= 75 and bool(action), score, reason or action
    except Exception as error:
        print(f"YouTube visual AI failed closed for source: {error}")
        if GEMINI_API_KEY:
            return False, 0, "visual AI unavailable; candidate rejected"
        return True, 0, "visual AI disabled"
    finally:
        for frame in frames:
            try:
                frame.unlink()
            except OSError:
                pass
        try:
            sample_dir.rmdir()
        except OSError:
            pass

def _gemini_generate_commentary(manifest, theme):
    """Write clip-specific reactions, then force a second AI comedy-editor pass."""
    if (
        not YOUTUBE_AI_SELECTOR_ENABLED
        or not GEMINI_API_KEY
        or os.getenv("GEMINI_ENABLED", "true").lower() != "true"
    ):
        return None

    candidates = []
    for i, source in enumerate(manifest):
        candidates.append({
            "id": i,
            "title": str(source.get("title", ""))[:160],
            "description": str(source.get("description", ""))[:260],
            "visible_action": str(source.get("_visual_ai_action", ""))[:220],
            "visual_hook": str(source.get("_visual_ai_hook", ""))[:180],
            "visual_judgement": str(source.get("_visual_ai_reason", ""))[:160],
        })

    banned = re.compile(
        r"\b(number|rank|top\s*10|coming in|at number|countdown|first|then|next|after|before|"
        r"meanwhile|eventually|suddenly|this clip|in this clip)\b", re.I
    )
    generic = re.compile(
        r"\b(that was (crazy|funny|wild|insane|ridiculous)|that timing was (perfect|"
        r"ridiculously good|genuinely hilarious)|what a reaction|that reaction (was|is) "
        r"(priceless|everything)|that went (completely )?wrong|that escalated)\b", re.I
    )

    def call_gemini(prompt, max_tokens=1200):
        response = _gemini_post(
            {"contents": [{"parts": [{"text": prompt}]}],
             "generationConfig": {
                 "temperature": 0.92,
                 "topP": 0.92,
                 "maxOutputTokens": max_tokens,
                 "response_mime_type": "application/json",
                 "response_schema": {
                     "type": "array",
                     "minItems": len(manifest),
                     "maxItems": len(manifest),
                     "items": {"type": "string"},
                 },
             }},
            timeout=40,
        )
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise ValueError("Gemini commentary returned no JSON")
        return json.loads(match.group(0))

    def validate(lines):
        if not isinstance(lines, list) or len(lines) != len(manifest):
            return False
        normalized, openings, trigrams = [], set(), set()
        for line in lines:
            line = re.sub(r"\s+", " ", str(line)).strip()
            words = re.findall(r"[A-Za-z0-9']+", line.lower())
            if not line or banned.search(line) or generic.search(line) or not (5 <= len(words) <= 13):
                return False
            compact = " ".join(words)
            opening = " ".join(words[:3])
            if opening in openings:
                return False
            grams = set(zip(words, words[1:], words[2:]))
            if trigrams & grams:
                return False
            if any(
                len(set(words) & set(old.split())) / max(1, min(len(words), len(old.split()))) >= 0.78
                for old in normalized
            ):
                return False
            openings.add(opening)
            trigrams |= grams
            normalized.append(compact)
        return True

    writer_prompt = (
        f"Write {len(manifest)} ORIGINAL one-line comedian reactions for a fast YouTube Top-10 {theme} Short. "
        "Each line maps to exactly one clip in order. React to the VISIBLE ACTION described by the visual judge. "
        "Do not narrate a story and do not describe what happened before/after. "
        "Do not mention rankings, numbers, the list, the clip, the video, or background facts. "
        "Use 5-13 natural spoken words. Make each line genuinely different: vary openings, verbs, rhythm, "
        "humor angle, and punchline. Use specific details when the visual evidence gives one. "
        "Prefer clever reactions, playful roasts, disbelief, awkward observations, or sharp one-liners. "
        "Never use generic filler such as 'that was crazy', 'that was funny', 'that timing was perfect', "
        "'what a reaction', 'that went wrong', or 'that escalated'. Return ONLY the JSON array."
        f"\nCLIP EVIDENCE:\n{json.dumps(candidates, ensure_ascii=False)}"
    );

    editor_prompt = (
        f"You are the FINAL comedy editor for a {theme} Top-10 Short. "
        "Rewrite the draft reactions so every line sounds like a different comedian reacting to a different moment. "
        "The visible-action evidence is authoritative. If a draft does not match the evidence, replace it. "
        "Keep 5-13 words per line. No story narration, no countdown language, no generic filler, no repeated "
        "openings, repeated three-word phrases, repeated joke structures, or near-duplicate vocabulary. "
        "Each line must contain a concrete reaction to something visible. Return ONLY the JSON array."
        f"\nVISUAL EVIDENCE:\n{json.dumps(candidates, ensure_ascii=False)}"
    );

    try:
        drafts = call_gemini(writer_prompt)
        edited = call_gemini(
            editor_prompt + f"\nDRAFT REACTIONS:\n{json.dumps(drafts, ensure_ascii=False)}",
            max_tokens=1400,
        )
        if not validate(edited):
            repair_prompt = (
                "FINAL REPAIR. Rewrite all reactions below. Keep the same order and visible-action meaning. "
                "Every line must be 5-13 words, clip-specific, funny, spoken naturally, and structurally unique. "
                "No countdown words, story transitions, generic filler, repeated openings, repeated trigrams, "
                "or near-duplicate vocabulary. Return ONLY the JSON array."
                f"\nEVIDENCE: {json.dumps(candidates, ensure_ascii=False)}"
                f"\nREACTIONS: {json.dumps(edited, ensure_ascii=False)}"
            );
            edited = call_gemini(repair_prompt, max_tokens=1500);
        if not validate(edited):
            raise ValueError("Gemini commentary failed strict diversity/quality validation")
        print("YouTube AI commentary: writer -> comedy editor -> diversity validator passed.")
        return [re.sub(r"\s+", " ", str(x)).strip() for x in edited]
    except Exception as error:
        print(f"YouTube AI commentary unavailable; using local anti-repeat fallback: {error}")
        return None

def _visual_preflight(path, duration, theme="most interesting"):
    """Reject black/frozen/low-information source videos before final clips."""
    sample_dir = Path(path).with_suffix("")
    sample_dir.mkdir(exist_ok=True)
    frames = []
    try:
        for pct in (0.2, 0.45, 0.7, 0.9):
            frame = sample_dir / f"qc_{int(pct * 100)}.jpg"
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error", "-ss", str(max(0.1, duration * pct)),
                "-i", str(path), "-frames:v", "1", "-vf", "scale=160:160", str(frame)
            ], check=True, timeout=6)
            frames.append(frame)
        from PIL import Image, ImageStat
        images = [Image.open(frame).convert("L") for frame in frames]
        means = [ImageStat.Stat(img).mean[0] for img in images]
        average_mean = sum(means) / len(means)
        if max(means) < 8:
            return False, "near-black footage"
        if average_mean < (12 if theme == "scariest" else 22):
            return False, "too dark for clear vertical viewing"
        diffs = []
        for a, b in zip(images, images[1:]):
            diffs.append(sum(abs(x - y) for x, y in zip(a.getdata(), b.getdata())) / (160 * 160))
        if max(means) - min(means) < 1.5 and max(diffs, default=0) < 1.0:
            return False, "frozen or nearly static footage"
            return False, "nearly frozen footage"
    except Exception as error:
        return False, f"visual QC error: {error}"
    finally:
        for frame in frames:
            try:
                frame.unlink()
            except OSError:
                pass
        try:
            sample_dir.rmdir()
        except OSError:
            pass
    return True, "passed"

def _topic_bucket(item):
    text = f"{item.get('title','')} {item.get('description','')}".lower()
    buckets = [
        ("motorcycle", ("motorcycle", "motorbike", "motocross", "dirt bike", "biker")),
        ("car", ("car", "cars", "rally", "race car", "racing")),
        ("skate", ("skateboard", "skateboarding", "skate")),
        ("bike", ("bicycle", "bike", "cycling", "cyclist")),
        ("crowd", ("crowd", "stadium", "public", "street")),
        ("people", ("people", "person", "man", "woman", "reaction")),
        ("water", ("surf", "water", "pool", "boat", "rafting")),
        ("stunt", ("stunt", "jump", "trick", "extreme")),
        ("sports", ("sport", "sports", "competition", "match")),
    ]
    for bucket, words in buckets:
        if any(word in text for word in words):
            return bucket
    return "other"


def _rank_and_diversify(sources, theme):
    """Rank relevant clips while enforcing provider and subject diversity."""
    ranked = sorted(sources, key=lambda item: item.get("_match_score", -999), reverse=True)
    chosen, used_keys, provider_counts, bucket_counts = [], set(), {}, {}

    def consider(item, strict_topics=True):
        if item.get("_match_score", -999) < 0:
            return False
        title = re.sub(r"[^a-z0-9]+", " ", str(item.get("title", "")).lower()).strip()
        description = re.sub(r"[^a-z0-9]+", " ", str(item.get("description", "")).lower()).strip()
        source_id = str(item.get("source_url") or item.get("url") or "").strip()
        identity = source_id or (title[:140], description[:80])
        if identity in used_keys:
            return False
        provider = item.get("provider", "unknown")
        if provider_counts.get(provider, 0) >= 8:
            return False
        bucket = _topic_bucket(item)
        if strict_topics and bucket_counts.get(bucket, 0) >= 4:
            return False
        chosen.append(item)
        used_keys.add(identity)
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        return True

    for item in ranked:
        if len(chosen) >= CLIPS_PER_VIDEO * 6:
            break
        consider(item, strict_topics=True)

    if len(chosen) < CLIPS_PER_VIDEO * 3:
        for item in ranked:
            if len(chosen) >= CLIPS_PER_VIDEO * 4:
                break
            consider(item, strict_topics=False)

    return chosen
def _listicle_commentary(number, opportunity, source):
    """Deterministic local fallback with clip evidence and anti-repeat-friendly phrasing."""
    theme = _listicle_theme(opportunity.get("trend", ""))
    evidence = str(source.get("_visual_ai_action", "")).strip()
    text = re.sub(r"\s+", " ", f"{source.get('title','')} {source.get('description','')} {evidence}").lower()

    def pick(lines):
        seed = hashlib.sha256(
            f"{number}|{source.get('source_url','')}|{source.get('title','')}|{evidence}".encode("utf-8")
        ).hexdigest()
        return lines[int(seed[:8], 16) % len(lines)]

    if theme == "funniest":
        if any(w in text for w in ("fall", "trip", "slip", "fail", "mistake", "mishap")):
            pool = [
                "That landing had absolutely zero cooperation.",
                "Bro committed to the mistake way too hard.",
                "The recovery attempt somehow made it worse.",
                "That face immediately says, 'I'm finished.'",
                "Gravity really picked the worst possible moment.",
                "You can actually see the regret arrive.",
            ]
        elif any(w in text for w in ("reaction", "shocked", "surprise", "scream", "laugh")):
            pool = [
                "That face changed before anyone could react.",
                "The expression alone deserves its own replay.",
                "That reaction came with absolutely no warning.",
                "Nobody could have rehearsed that response.",
                "The facial expression completely steals the moment.",
                "That reaction landed harder than the actual joke.",
            ]
        else:
            pool = [
                "That decision aged terribly in real time.",
                "The confidence lasted approximately three seconds.",
                "There was a plan here. It did not survive.",
                "That move needed about ten seconds more thinking.",
                "The commitment is impressive; the result is not.",
                "That is an elite level of bad timing.",
            ]
    elif theme == "scariest":
        pool = [
            "That reaction says everything without a single word.",
            "The mood changed instantly when that appeared.",
            "That is exactly when I'd leave the room.",
            "Nobody looks prepared for what they're seeing.",
            "The expression tells you how serious that felt.",
            "That moment got uncomfortable incredibly fast.",
        ]
    else:
        pool = [
            "That took a turn nobody was ready for.",
            "The margin for error there was basically nothing.",
            "That move had absolutely no room for mistakes.",
            "The speed makes this look completely unreal.",
            "One tiny mistake and everything changes instantly.",
            "That is way more chaotic than it needed to be.",
        ]
    return pick(pool)

def _tts(text, path, voice_id=None, label="Voice 1"):
    """Generate narration with the explicitly selected ElevenLabs voice."""
    if TTS_ENGINE in {"none", "text"}:
        return None

    selected_voice = (voice_id or ELEVENLABS_VOICE_ID_1).strip()
    if ELEVENLABS_ENABLED and ELEVENLABS_API_KEY and selected_voice:
        try:
            endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{selected_voice}"
            response = requests.post(
                endpoint,
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"},
                json={"text": text, "model_id": ELEVENLABS_MODEL, "voice_settings": {"stability": 0.34, "similarity_boost": 0.78, "style": 0.48, "use_speaker_boost": True}, "speed": 1.45},
                timeout=120,
            )
            response.raise_for_status()
            if not response.content.startswith(b"ID3") and not response.content.startswith(b"\xff\xfb"):
                raise ValueError("ElevenLabs returned unexpected audio data")
            path.write_bytes(response.content)
            print(f"YouTube TTS: ElevenLabs {label} generated successfully.")
            return str(path)
        except Exception as error:
            print(f"YouTube TTS: ElevenLabs {label} failed: {error}")
            if ELEVENLABS_TEST_VOICES:
                raise RuntimeError(f"ElevenLabs {label} test failed") from error

    if ELEVENLABS_TEST_VOICES and ELEVENLABS_ENABLED:
        raise RuntimeError(f"ElevenLabs {label} test could not run: voice ID or API key is missing.")

    try:
        if TTS_ENGINE in {"auto", "edge", "edge-tts"}:
            import asyncio
            import edge_tts
            async def make():
                await edge_tts.Communicate(text, TTS_VOICE, rate="+75%").save(str(path))
            asyncio.run(make())
            print("YouTube TTS: fast edge-tts fallback generated successfully.")
            return str(path)
    except Exception as error:
        print(f"YouTube TTS fallback failed: {error}")
    return None


def create_youtube_commentary_video(opportunity, index):
    root = Path(OUTPUT_DIR) / f"youtube_{index}"
    root.mkdir(parents=True, exist_ok=True)
    query = opportunity.get("trend") or "funniest moments caught on camera"
    theme = opportunity.get("listicle_theme") or _listicle_theme(query)
    if theme == "funniest":
        query = "funniest moments caught on camera"
    elif theme == "scariest":
        query = "scariest moments caught on camera"
    elif theme == "wildest":
        query = "wildest moments caught on camera"
    search_limit = max(CLIPS_PER_VIDEO * 6, 60)
    if theme == "funniest":
        # Search for actual human-action moments, not generic "funny" stock.
        # The old broad queries produced unrelated animals/stock footage in Run 406.
        queries = [
            "human funny fail caught on camera",
            "people instant regret funny fail",
            "unexpected human reaction funny moment",
            "perfectly timed human fail reaction",
            "funny public mishap people reaction",
            "people falling harmless funny fail",
            "awkward human moment caught camera",
            "funny sports fail human reaction",
        ]
    elif theme == "scariest":
        queries = [
            "scared people caught on camera",
            "ghost caught on camera",
            "haunted house scary footage",
            "creepy night encounter people",
            "security camera scary incident",
            "people screaming scary moment",
            "eerie unexplained footage",
            "horror reaction caught camera",
        ]
    elif theme == "wildest":
        queries = [
            "wild people moments caught on camera",
            "crazy accidents and near misses caught on camera",
            "extreme stunts and unexpected fails",
            "shocking public reactions and chaos",
            "wild sports moments and close calls",
            "unexpected street stunts and crashes",
            "crazy vehicle moments and crashes",
            "wild crowd reactions and public moments",
        ]
    else:
        # For live trends, search the actual trend first. The old implementation
        # ignored the trend and repeatedly searched generic reaction stock.
        clean_query = re.sub(r"[^A-Za-z0-9ÅÄÖåäö0-9'’\- ]+", " ", str(query)).strip()
        clean_query = re.sub(r"\s+", " ", clean_query)[:100]
        queries = [
            f"{clean_query} real footage",
            f"{clean_query} people reaction",
            f"{clean_query} caught on camera",
            f"{clean_query} viral moment",
            f"{clean_query} news footage",
            f"{clean_query} real life moment",
        ]

    fallback_queries = {
        "funniest": [
            "human funny fail", "people funny accident", "instant regret human",
            "funny reaction people", "harmless public fail", "awkward human moment",
            "unexpected human reaction", "funny sports fail", "people comedy mishap",
            "perfect timing fail",
        ],
        "scariest": [
            "scary moments people", "creepy moments caught camera", "people scared reaction",
            "ghost footage", "haunted scary footage", "security camera incident",
            "night scary encounter", "strange unexplained moment", "eerie people reaction",
            "unexpected scary event", "people screaming",
        ],
        "wildest": [
            "wild moments people", "crazy moments caught camera", "unexpected accident reaction",
            "extreme stunt reaction", "shocking event people", "dramatic near miss",
            "chaotic crowd moment", "unexpected real life event",
        ],
        "most interesting": [
            "interesting people moments", "unexpected people reaction", "real life surprising moments",
            "people caught on camera", "unusual real life event", "interesting reaction people",
        ],
    }
    shard_index = max(1, int(index))
    ai_queries = _gemini_expand_search_queries(theme, shard_index)
    # Rotate both AI and built-in queries by shard so parallel jobs research different angles.
    if ai_queries:
        rotation = (shard_index - 1) % len(ai_queries)
        ai_queries = ai_queries[rotation:] + ai_queries[:rotation]
    built_in_queries = queries[shard_index - 1:] + queries[:shard_index - 1]
    fallback = fallback_queries.get(theme, [])
    search_waves = ai_queries + built_in_queries + fallback[shard_index - 1:] + fallback[:shard_index - 1]
    sources, seen = [], set()
    for wave_index, search_query in enumerate(search_waves):
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
            item["_search_query"] = search_query
            item["_match_score"] = _source_score(item, query)
            sources.append(item)
        if len(sources) >= CLIPS_PER_VIDEO * 30:
            break

    # Prevent the system from recycling the same clips forever.
    # Previous selections are remembered across runs, while the three parallel shards
    # are split deterministically so they cannot choose the exact same URL in one run.
    history = _load_source_history()
    shard_index = max(1, int(index))
    fresh_sources = []
    shard_sources = []
    for item in sources:
        key = str(item.get("source_url") or item.get("url") or "")
        if key and key in history:
            continue
        digest = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) if key else 0
        if digest % 3 == (shard_index - 1):
            shard_sources.append(item)
        else:
            fresh_sources.append(item)
    # HARD BATCH ISOLATION: the three YouTube matrix jobs run in parallel.
    # Never fall back to another shard's candidates, otherwise Video 1/2/3 can
    # select the exact same source URL. If this shard is short, fail clearly
    # rather than silently reusing footage.
    required_candidates = max(CLIPS_PER_VIDEO * 8, 80)
    sources = shard_sources
    print(
        f"YouTube research freshness: {len(history)} historical sources excluded; "
        f"{len(sources)} candidates belong exclusively to shard {shard_index}."
    )
    if len(sources) < required_candidates:
        raise RuntimeError(
            f"YouTube shard {shard_index} has only {len(sources)} fresh exclusive candidates; "
            f"need at least {required_candidates}. Refusing cross-shard fallback to prevent "
            "Video 1/2/3 from reusing footage. Increase search diversity/providers instead."
        )

    # Fast path: local ranking first, then let Gemini judge only the strongest candidates.
    locally_ranked = _rank_and_diversify(sources, theme)
    ranked_all = sorted(sources, key=lambda item: item.get("_match_score", -999), reverse=True)
    ai_pool = _rank_and_diversify(ranked_all, theme)[:AI_SELECTOR_CANDIDATES]
    judged_pool = _gemini_rank_sources(ai_pool, theme)
    # Keep the strong local candidates that Gemini did not judge as a replacement
    # pool. A temporary Gemini 429 or a visual/duration rejection must never leave
    # us with only the small AI shortlist.
    judged_keys = {item.get("source_url") or item.get("url") for item in judged_pool}
    replacement_pool = [
        item for item in ranked_all
        if (item.get("source_url") or item.get("url")) not in judged_keys
    ]
    # Do not let the AI shortlist become the whole candidate pool. We need
    # enough real clips for download/duration/visual QC, while still preferring
    # relevance. Keep the strongest replacements even when their metadata score
    # is modest; visual/download QC is the next gate.
    eligible_replacements = [
        item for item in replacement_pool
        if item.get("_match_score", -999) >= 0
    ]
    sources = (judged_pool + eligible_replacements)[:max(CLIPS_PER_VIDEO * 24, 240)]

    clips, manifest = [], []
    visual_qc_count = 0
    used_source_keys = set()
    for clip_index, source in enumerate(sources):
        if len(clips) >= CLIPS_PER_VIDEO:
            break
        if source.get("_match_score", -999) < 0:
            print(f"YouTube relevance QC rejected source: {source.get('title','unknown')} (score={source.get('_match_score', -999):.1f})")
            continue
        if not _strict_source_gate(source, theme):
            print(f"YouTube strict semantic QC rejected source: {source.get('title','unknown')}")
            continue
        source_text=f"{source.get('title','')} {source.get('description','')} {source.get('_search_query','')}".lower()
        if _youtube_topic_is_unrelated(source_text,theme):
            print(f"YouTube topic QC rejected unrelated subject: {source.get('title','unknown')}")
            continue
        # Keep this second visual-text pass for defense in depth.
        if any(term in source_text for term in ("astronomy", "galaxy", "cosmos", "comet", "asteroid", "milky way", "live wallpaper")):
            print(f"YouTube visual semantic QC rejected generic source: {source.get('title','unknown')}")
            continue
        source_key = source.get("source_url") or source.get("url")
        if source_key in used_source_keys:
            continue
        used_source_keys.add(source_key)
        raw = root / f"source_{clip_index}_{_safe_name(source['title'])}.mp4"
        segment = root / f"segment_{clip_index}.mp4"
        try:
            _download(source["url"], raw)
            duration = _probe_duration(raw)
            if duration < CLIP_SECONDS + 0.5:
                continue
            max_start = max(0.0, duration - CLIP_SECONDS)
            starts = [0.03 * duration, 0.16 * duration, 0.30 * duration, 0.44 * duration, 0.58 * duration, 0.72 * duration, 0.84 * duration]
            start = min(starts[clip_index % len(starts)], max_start)
            if GEMINI_VISUAL_QC_LIMIT > 0 and visual_qc_count < GEMINI_VISUAL_QC_LIMIT:
                visual_qc_count += 1
                ai_ok, ai_score, ai_reason = _gemini_visual_judge(raw, theme, source, clip_start=start)
                if not ai_ok:
                    print(f"YouTube visual AI rejected source: {source.get('title','unknown')} (score={ai_score}; {ai_reason})")
                    continue
            if visual_qc_count < VISUAL_QC_LIMIT:
                visual_qc_count += 1
                visual_ok, visual_reason = _visual_preflight(raw, duration, theme)
            else:
                visual_ok, visual_reason = True, "QC shortlist limit reached"
            if not visual_ok:
                print(f"YouTube visual QC rejected source: {source.get('title','unknown')} ({visual_reason})")
                continue
            # Keep source/timestamp so clips can be ranked after visual AI review.
            clean_source = dict(source)
            clean_source.pop("_match_score", None)
            clean_source["_selection_score"] = source.get("_match_score", 0)
            clean_source["_raw_path"] = str(raw)
            clean_source["_clip_start"] = start
            clean_source["_clip_segment"] = str(segment)
            manifest.append(clean_source)
            clips.append(segment)
        except (requests.RequestException, subprocess.CalledProcessError, ValueError, OSError) as error:
            print(f"YouTube clip skipped: {source.get('title','unknown')} ({source.get('provider','unknown')}): {error}")
            continue

    if len(clips) < CLIPS_PER_VIDEO:
        raise RuntimeError(
            f"YouTube video #{index} produced only {len(clips)} usable clips; need {CLIPS_PER_VIDEO}. "
            f"Searched {len(search_waves)} queries and evaluated {len(sources)} candidates; "
            "the remaining candidates failed duration/download/visual/relevance QC."
        )

    # FINAL QUALITY RANKING: strongest accepted clip becomes #1.
    def _final_rank_score(source):
        visual = float(source.get("_visual_ai_score", 0) or 0)
        local = float(source.get("_selection_score", 0) or 0)
        local_norm = max(0.0, min(100.0, 50.0 + local))
        if visual > 0:
            return FINAL_RANK_VISUAL_WEIGHT * visual + FINAL_RANK_LOCAL_WEIGHT * local_norm
        return local_norm

    ranked_manifest = sorted(
        manifest,
        key=lambda source: (
            _final_rank_score(source),
            float(source.get("_visual_ai_score", 0) or 0),
            float(source.get("_selection_score", 0) or 0),
        ),
        reverse=True,
    )

    # Keep adjacent ranks visually diverse when possible.
    reordered = []
    remaining = list(ranked_manifest)
    while remaining:
        if not reordered:
            reordered.append(remaining.pop(0))
            continue
        previous_bucket = _topic_bucket(reordered[-1])
        different = [x for x in remaining if _topic_bucket(x) != previous_bucket]
        pool = different if different else remaining
        chosen = max(pool, key=_final_rank_score)
        remaining.remove(chosen)
        reordered.append(chosen)

    manifest = list(reversed(reordered))
    rerendered_clips = []
    for position, source in enumerate(manifest, start=1):
        rank = CLIPS_PER_VIDEO - position + 1
        segment = root / f"ranked_segment_{rank}.mp4"
        _make_clip(source["_raw_path"], segment, float(source["_clip_start"]), CLIP_SECONDS, rank=rank)
        source["_rank"] = rank
        source["_final_rank_score"] = round(_final_rank_score(source), 2)
        source["_clip_segment"] = str(segment)
        rerendered_clips.append(segment)
    clips = rerendered_clips

    title_card = root / "title_card.mp4"
    if theme == "funniest":
        title_text = "TOP 10 FUNNIEST MOMENTS"
    elif theme == "scariest":
        title_text = "TOP 10 SCARIEST MOMENTS"
    elif theme == "wildest":
        title_text = "TOP 10 WILDEST MOMENTS"
    else:
        title_text = "TOP 10 MOMENTS"
    # The first real clip is the hook. No black intro card.
    combined_clips = clips
    combined = root / "combined.mp4"
    inputs, filter_parts = [], []
    for i, item in enumerate(combined_clips):
        inputs += ["-i", str(item)]
        filter_parts.append(
            f"[{i}:v:0]fps=30,scale=1080:1920,setsar=1,settb=1/30,format=yuv420p[v{i}]"
        )
    concat_inputs = "".join(f"[v{i}]" for i in range(len(combined_clips)))
    filter_parts.append(
        f"{concat_inputs}concat=n={len(combined_clips)}:v=1:a=0,settb=1/30,format=yuv420p[vout]"
    )
    subprocess.run([
        "ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]", "-an", "-r", "30", "-c:v", "libx264",
        "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(combined)
    ], check=True, timeout=180)

    _save_source_history([
        source.get("source_url") or source.get("url")
        for source in manifest
    ])
    comments = _gemini_generate_commentary(manifest, theme)
    if comments:
        print("YouTube narration: REAL AI scriptwriter is active.")
    else:
        print("YouTube narration: AI unavailable; using varied local fallback.")
        comments = [_listicle_commentary(CLIPS_PER_VIDEO - i, opportunity, source) for i, source in enumerate(manifest)]
    full_commentary = " ".join(comments)

    if ELEVENLABS_TEST_VOICES and ELEVENLABS_ENABLED and index == 1:
        if not ELEVENLABS_VOICE_ID_1 or not ELEVENLABS_VOICE_ID_2:
            raise RuntimeError("Voice test requires ELEVENLABS_VOICE_ID_1 and ELEVENLABS_VOICE_ID_2.")
        _tts(full_commentary, root / "voice1_sample.mp3", ELEVENLABS_VOICE_ID_1, "Voice 1")
        _tts(full_commentary, root / "voice2_sample.mp3", ELEVENLABS_VOICE_ID_2, "Voice 2")
        print("YouTube TTS: both ElevenLabs voice samples generated for direct comparison.")

    audio = root / "commentary.mp3"
    audio_path = _tts(full_commentary, audio, ELEVENLABS_VOICE_ID_1, "Voice 1")

    final = Path(OUTPUT_DIR) / f"youtube_commentary_{index}.mp4"
    if audio_path and YOUTUBE_MODE != "text":
        target_duration = max(0.1, TITLE_SECONDS + (CLIPS_PER_VIDEO * CLIP_SECONDS))
        audio_duration = _probe_duration(audio_path)
        # Never slow a short voice track down. Only speed up when narration overruns
        # the visual timeline; otherwise keep the fast voice and pad the tail slightly.
        tempo_ratio = max(1.0, min(2.0, audio_duration / target_duration))
        audio_filter = f"atempo={tempo_ratio:.4f},loudnorm=I=-16:TP=-1.5:LRA=11,apad=pad_dur=0.35"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(combined), "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            "-af", audio_filter, "-ar", "48000", "-b:a", "128k",
            "-t", f"{target_duration:.3f}", "-movflags", "+faststart", str(final)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        mode = "ai_voice"
    else:
        subtitle = root / "commentary.srt"
        cursor = TITLE_SECONDS
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
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        mode = "text"

    metadata = {
        "platform": "youtube", "mode": mode, "format": "top_10_listicle",
        "trend": opportunity.get("trend", ""), "commentary": comments,
        "editing": {
            "clips": CLIPS_PER_VIDEO, "clip_seconds": CLIP_SECONDS,
            "title_card_seconds": 0, "countdown": "#10 -> #1",
            "ranking_engine": "post-visual evidence ranking; strongest accepted clip is #1",
            "aspect_ratio": "9:16", "burned_in_text": True,
            "title_card": title_text, "rank_overlay": True,
            "selection_engine": "AI query planner -> multi-provider research -> persistent freshness/history -> strict real-footage gate -> local relevance -> Gemini multi-frame vision casting -> visual preflight -> diversity",
            "ai_selector": bool(YOUTUBE_AI_SELECTOR_ENABLED and GEMINI_API_KEY),
            "visual_preflight": True, "ai_selector_candidates": AI_SELECTOR_CANDIDATES, "visual_qc_limit": VISUAL_QC_LIMIT, "gemini_visual_qc_limit": GEMINI_VISUAL_QC_LIMIT, "freshness_history": True, "ai_search_planner": bool(YOUTUBE_AI_SELECTOR_ENABLED and GEMINI_API_KEY and os.getenv("GEMINI_ENABLED", "true").lower() == "true"),
            "commentary_style": "ai_writer_plus_always_on_comedy_editor_plus_strict_anti_repetition_validation", "voice_rate": "edge +75% / ElevenLabs 1.45x",
        },
        "sources": [{k:v for k,v in source.items() if k != "_raw_path"} for source in manifest],
        "license_policy": (
            "Automated sources are limited to Wikimedia Commons items with license metadata, "
            "Pexels, Pixabay, and Internet Archive items whose metadata identifies a Creative Commons/public-domain license. "
            "Mixkit is not automated because its current terms prohibit scripts/bots from mass-downloading items."
        ),
    }
    meta_path = Path(OUTPUT_DIR) / f"youtube_commentary_{index}.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(final), str(meta_path)
