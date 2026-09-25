import os
import json
import requests

YOUTUBE_ACCESS_TOKEN = os.getenv("YOUTUBE_ACCESS_TOKEN", "")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "")
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "")
PUBLISH_ENABLED = os.getenv("PUBLISH_ENABLED", "false").lower() == "true"
PUBLISH_PRIVACY = os.getenv("PUBLISH_PRIVACY", "private")

def _youtube(video_path, title, description, tags):
    token = YOUTUBE_ACCESS_TOKEN
    try:
        if YOUTUBE_REFRESH_TOKEN and YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET:
            refresh = requests.post(
                "https://oauth2.googleapis.com/token",
                data={"client_id": YOUTUBE_CLIENT_ID, "client_secret": YOUTUBE_CLIENT_SECRET,
                      "refresh_token": YOUTUBE_REFRESH_TOKEN, "grant_type": "refresh_token"},
                timeout=30,
            )
            refresh.raise_for_status()
            token = refresh.json().get("access_token", token)
        if not token:
            return {"enabled": False, "status": "waiting_for_youtube_oauth"}
        metadata = {
            "snippet": {"title": title[:100], "description": description, "tags": tags[:15], "categoryId": "22"},
            "status": {"privacyStatus": PUBLISH_PRIVACY, "selfDeclaredMadeForKids": False}
        }
        init = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"part": "snippet,status", "uploadType": "resumable"},
            headers={"Authorization": f"Bearer {YOUTUBE_ACCESS_TOKEN}", "Content-Type": "application/json; charset=UTF-8"},
            json=metadata, timeout=30,
        )
        init.raise_for_status()
        upload_url = init.headers.get("Location")
        if not upload_url:
            return {"enabled": True, "status": "upload_url_missing"}
        with open(video_path, "rb") as video:
            upload = requests.put(upload_url, headers={"Content-Type": "video/mp4"}, data=video, timeout=300)
        upload.raise_for_status()
        data = upload.json()
        return {"enabled": True, "status": "published", "video_id": data.get("id")}
    except Exception as error:
        return {"enabled": True, "status": "error", "error": str(error)}

def _tiktok(video_path, caption):
    if not TIKTOK_ACCESS_TOKEN:
        return {"enabled": False, "status": "waiting_for_tiktok_oauth"}
    try:
        size = os.path.getsize(video_path)
        chunk = min(max(5 * 1024 * 1024, size), 64 * 1024 * 1024)
        total = (size + chunk - 1) // chunk
        init = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {TIKTOK_ACCESS_TOKEN}", "Content-Type": "application/json"},
            json={"post_info": {"title": caption[:2200], "privacy_level": "SELF_ONLY", "is_aigc": True},
                  "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}},
            timeout=30,
        )
        init.raise_for_status()
        data = init.json().get("data", {})
        upload_url, publish_id = data.get("upload_url"), data.get("publish_id")
        if not upload_url:
            return {"enabled": True, "status": "upload_url_missing"}
        with open(video_path, "rb") as video:
            sent = 0
            while sent < size:
                block = video.read(chunk)
                end = sent + len(block) - 1
                response = requests.put(
                    upload_url,
                    headers={"Content-Type": "video/mp4", "Content-Length": str(len(block)),
                             "Content-Range": f"bytes {sent}-{end}/{size}"},
                    data=block, timeout=300,
                )
                response.raise_for_status()
                sent = end + 1
        return {"enabled": True, "status": "submitted", "publish_id": publish_id}
    except Exception as error:
        return {"enabled": True, "status": "error", "error": str(error)}

def publish(video_path: str, metadata=None):
    metadata = metadata or {}
    title = str(metadata.get("title") or "Viral Short")
    caption = str(metadata.get("caption") or title)
    description = str(metadata.get("description") or caption)
    tags = metadata.get("hashtags") or ["shorts", "trending"]
    if not PUBLISH_ENABLED:
        return {
            "youtube": {"enabled": False, "status": "dry_run"},
            "tiktok": {"enabled": False, "status": "dry_run"},
            "video": video_path,
        }
    return {
        "youtube": _youtube(video_path, title, description, tags),
        "tiktok": _tiktok(video_path, caption),
        "video": video_path,
    }
