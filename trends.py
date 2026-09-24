import os
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
TIKTOK_RESEARCH_TOKEN = os.getenv("TIKTOK_RESEARCH_TOKEN", "")


def _normalize(value):
    value = re.sub(r"[^a-z0-9 ]+", " ", str(value).lower())
    return " ".join(value.split())


def _similar(a, b):
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.78


def _add(trends, value, source, score=0.0, metrics=None):
    if not value:
        return
    metrics = metrics or {}
    for item in trends:
        if _similar(value, item["trend"]):
            item["score"] = max(item.get("score", 0.0), score)
            item.setdefault("sources", [])
            if source not in item["sources"]:
                item["sources"].append(source)
            for key, metric in metrics.items():
                if isinstance(metric, (int, float)):
                    item.setdefault("metrics", {})[key] = max(item.get("metrics", {}).get(key, 0), metric)
                elif metric:
                    item.setdefault("metrics", {})[key] = metric
            return
    trends.append({
        "trend": value,
        "source": source,
        "sources": [source],
        "score": round(score, 3),
        "metrics": metrics,
    })


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
            for rank, item in enumerate(root.findall(".//item")):
                title = item.find("title")
                if title is not None and title.text:
                    value = title.text.strip()
                    if " - " in value:
                        value = value.rsplit(" - ", 1)[0]
                    score = max(25.0, 100.0 - rank * 2.0)
                    _add(trends, value, "google", score, {"rank": rank + 1})
        except Exception as error:
            print(f"Google source failed: {error}")
    return trends


def get_youtube_trends():
    if not YOUTUBE_API_KEY:
        print("YouTube scanner skipped: YOUTUBE_API_KEY is not configured.")
        return []

    trends = []
    try:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "regionCode": "SE",
                "maxResults": 25,
                "key": YOUTUBE_API_KEY,
            },
            timeout=20,
        )
        response.raise_for_status()
        for rank, item in enumerate(response.json().get("items", [])):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            title = snippet.get("title", "").strip()
            views = int(stats.get("viewCount", 0))
            if title:
                score = min(100.0, 65.0 + (25.0 / max(1, rank + 1)) + min(20.0, views / 2_000_000))
                _add(
                    trends,
                    title,
                    "youtube",
                    score,
                    {"views": views, "rank": rank + 1},
                )
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
    params = {"fields": "id,video_description,view_count,like_count,comment_count,share_count,hashtag_names"}
    try:
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=30)
        response.raise_for_status()
        for rank, item in enumerate(response.json().get("data", {}).get("videos", [])):
            description = (item.get("video_description") or "").strip()
            views = int(item.get("view_count", 0))
            likes = int(item.get("like_count", 0))
            shares = int(item.get("share_count", 0))
            if description:
                score = min(100.0, 70.0 + min(20.0, views / 2_000_000) + min(10.0, shares / 100_000))
                _add(
                    trends,
                    description[:180],
                    "tiktok",
                    score,
                    {"views": views, "likes": likes, "shares": shares, "rank": rank + 1},
                )
    except Exception as error:
        print(f"TikTok source failed: {error}")
    return trends


def get_trends():
    combined = []
    for source in (get_news_trends(), get_youtube_trends(), get_tiktok_trends()):
        for item in source:
            _add(
                combined,
                item["trend"],
                item["source"],
                item.get("score", 0.0),
                item.get("metrics", {}),
            )

    # Reward cross-platform confirmation, then keep source diversity.
    for item in combined:
        sources = set(item.get("sources", []))
        metrics = item.get("metrics", {})
        cross_platform_bonus = max(0, len(sources) - 1) * 8
        engagement_bonus = min(8.0, metrics.get("shares", 0) / 50000 + metrics.get("likes", 0) / 500000 + metrics.get("views", 0) / 5000000)
        item["score"] = round(min(100.0, item.get("score", 0.0) + cross_platform_bonus + engagement_bonus), 3)
        item["confidence"] = round(min(1.0, 0.45 + 0.15 * len(sources) + min(0.4, item["score"] / 250)), 3)

    ranked = sorted(combined, key=lambda x: x.get("score", 0), reverse=True)
    selected = []
    source_counts = {}
    for item in ranked:
        source = item.get("source", "unknown")
        if source_counts.get(source, 0) >= 4:
            continue
        selected.append(item)
        source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) >= 10:
            break
    return selected


if __name__ == "__main__":
    trends = get_trends()
    print("\n🔥 TOP 10 CURRENT TOPICS IN SWEDEN\n")
    for number, item in enumerate(trends, 1):
        print(f"{number}. [{item['source']}] score={item['score']} confidence={item.get('confidence', 0)}: {item['trend']}")
