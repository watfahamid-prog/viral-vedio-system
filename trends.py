import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
TIKTOK_RESEARCH_TOKEN = os.getenv("TIKTOK_RESEARCH_TOKEN", "")


def _add(trends, value, source):
    if value and value not in [x["trend"] for x in trends]:
        trends.append({"trend": value, "source": source})


def get_news_trends():
    sources = [
        "https://news.google.com/rss?hl=sv&gl=SE&ceid=SE:sv",
        "https://trends.google.com/trending/rss?geo=SE",
    ]
    trends = []
    for url in sources:
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for item in root.findall(".//item"):
                title = item.find("title")
                if title is not None and title.text:
                    value = title.text.strip()
                    if value and value != "...":
                        if " - " in value:
                            value = value.rsplit(" - ", 1)[0]
                        _add(trends, value, "google")
        except Exception as error:
            print(f"Google source failed: {error}")
    return trends


def get_youtube_trends():
    if not YOUTUBE_API_KEY:
        print("YouTube scanner skipped: YOUTUBE_API_KEY is not configured.")
        return []

    trends = []
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": "SE",
        "maxResults": 25,
        "key": YOUTUBE_API_KEY,
    }
    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        for item in response.json().get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            title = snippet.get("title", "").strip()
            views = int(stats.get("viewCount", 0))
            if title:
                _add(trends, f"{title} | {views:,} views", "youtube")
    except Exception as error:
        print(f"YouTube source failed: {error}")
    return trends


def get_tiktok_trends():
    if not TIKTOK_RESEARCH_TOKEN:
        print("TikTok scanner skipped: TIKTOK_RESEARCH_TOKEN is not configured.")
        return []

    trends = []
    url = "https://open.tiktokapis.com/v2/research/video/query/"
    headers = {
        "Authorization": f"Bearer {TIKTOK_RESEARCH_TOKEN}",
        "Content-Type": "application/json",
    }
    # Research API access is restricted to approved eligible researchers.
    payload = {
        "query": {
            "and": [
                {"operation": "EQ", "field_name": "region_code", "field_values": ["SE"]}
            ]
        },
        "start_date": (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y%m%d"),
        "end_date": datetime.now(timezone.utc).strftime("%Y%m%d"),
        "max_count": 20,
        "cursor": 0,
    }
    params = {
        "fields": "id,video_description,view_count,like_count,comment_count,share_count,hashtag_names"
    }
    try:
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=30)
        response.raise_for_status()
        for item in response.json().get("data", {}).get("videos", []):
            description = (item.get("video_description") or "").strip()
            views = int(item.get("view_count", 0))
            if description:
                _add(trends, f"{description[:180]} | {views:,} views", "tiktok")
    except Exception as error:
        print(f"TikTok source failed: {error}")
    return trends


def get_trends():
    combined = []
    for source in (get_news_trends(), get_youtube_trends(), get_tiktok_trends()):
        for item in source:
            _add(combined, item["trend"], item["source"])

    # Keep the strongest/most recent-looking items while preserving source diversity.
    return combined[:10]


if __name__ == "__main__":
    trends = get_trends()
    print("\n🔥 TOP 10 CURRENT TOPICS IN SWEDEN\n")
    if not trends:
        print("No topics found.")
    else:
        for number, item in enumerate(trends, 1):
            print(f"{number}. [{item['source']}] {item['trend']}")
