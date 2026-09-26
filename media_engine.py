import os
from pathlib import Path
from urllib.parse import quote
import requests

ZERO_COST_MODE = os.getenv("ZERO_COST_MODE", "false").lower() == "true"
KEY = os.getenv("POLLINATIONS_API_KEY", "").strip()
BASE = os.getenv("POLLINATIONS_BASE_URL", "https://gen.pollinations.ai").rstrip("/")
IMAGE_MODEL = os.getenv("POLLINATIONS_IMAGE_MODEL", "flux").strip()
VIDEO_MODEL = os.getenv("POLLINATIONS_VIDEO_MODEL", "wan-fast").strip()
IMAGE_ENABLED = os.getenv("POLLINATIONS_IMAGE_ENABLED", "true").lower() == "true"
VIDEO_ENABLED = os.getenv("POLLINATIONS_VIDEO_ENABLED", "true").lower() == "true"
MAX_IMAGES_PER_VIDEO = max(0, int(os.getenv("POLLINATIONS_MAX_IMAGES_PER_VIDEO", "6")))
MAX_VIDEOS_PER_VIDEO = max(0, int(os.getenv("POLLINATIONS_MAX_MOTION_CLIPS_PER_VIDEO", "2")))
VIDEO_SECONDS = max(2, min(5, int(os.getenv("POLLINATIONS_VIDEO_SECONDS", "4"))))


def available():
    return bool(KEY) and not ZERO_COST_MODE


def _headers():
    return {"Authorization": f"Bearer {KEY}", "User-Agent": "viral-video-system/1.0"}


def generate_image(prompt, output_path, index=0):
    if ZERO_COST_MODE or not (KEY and IMAGE_ENABLED and index < MAX_IMAGES_PER_VIDEO):
        return None
    params = {"model": IMAGE_MODEL, "width": 768, "height": 1365, "nologo": "true"}
    url = f"{BASE}/image/{quote(prompt, safe='')}"
    try:
        response = requests.get(url, params=params, headers=_headers(), timeout=90)
        response.raise_for_status()
        if not response.content or len(response.content) < 20000:
            return None
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return str(path)
    except Exception as error:
        print(f"Pollinations image skipped: {error}")
        return None


def generate_video(prompt, output_path, index=0, duration=None):
    if ZERO_COST_MODE or not (KEY and VIDEO_ENABLED and index < MAX_VIDEOS_PER_VIDEO):
        return None
    duration = duration or VIDEO_SECONDS
    params = {"model": VIDEO_MODEL, "duration": max(2, min(5, int(duration)))}
    url = f"{BASE}/video/{quote(prompt, safe='')}"
    try:
        response = requests.get(url, params=params, headers=_headers(), timeout=300)
        response.raise_for_status()
        if not response.content or len(response.content) < 50000:
            return None
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return str(path)
    except Exception as error:
        print(f"Pollinations video skipped: {error}")
        return None
