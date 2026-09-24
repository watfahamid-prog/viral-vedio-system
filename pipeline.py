from datetime import datetime, timezone
from config import DRY_RUN, MAX_TRENDS, VIDEO_COUNT
from trends import get_trends


def _category(text):
    value = str(text).lower()
    if any(w in value for w in ["football", "soccer", "match", "goal", "sport", "league"]):
        return "sports"
    if any(w in value for w in ["iphone", "android", "ai", "tech", "app", "google", "microsoft", "openai"]):
        return "technology"
    if any(w in value for w in ["movie", "film", "series", "actor", "music", "song", "celebrity"]):
        return "entertainment"
    return "general"


def _format_for_run(index, source):
    # Always produce a deliberate platform mix in one run.
    if index == 0:
        return "youtube_ranked_breakdown"
    if index == 1:
        return "tiktok_cantina_story"
    if source == "google":
        return "youtube_quick_explainer"
    return "short_explainer"


def _platform_for_format(format_name):
    if format_name.startswith("youtube_"):
        return "youtube"
    if format_name.startswith("tiktok_"):
        return "tiktok"
    return "shorts"


def build_opportunities(trends):
    hooks = {
        "youtube_ranked_breakdown": "Here are the key things to know about {trend}.",
        "tiktok_cantina_story": "Wait, this is what is happening with {trend}.",
        "youtube_quick_explainer": "Here is the quick update on {trend}.",
        "short_explainer": "Here is the quick breakdown of {trend}.",
    }
    opportunities = []
    for index, item in enumerate(trends[:MAX_TRENDS]):
        trend = item["trend"] if isinstance(item, dict) else item
        source = item.get("source", "unknown") if isinstance(item, dict) else "unknown"
        format_name = _format_for_run(index, source)
        opportunities.append({
            "trend": trend,
            "source": source,
            "score": item.get("score", 0) if isinstance(item, dict) else 0,
            "sources": item.get("sources", [source]) if isinstance(item, dict) else [source],
            "metrics": item.get("metrics", {}) if isinstance(item, dict) else {},
            "category": _category(trend),
            "hook": hooks[format_name].format(trend=trend),
            "format": format_name,
            "platform": _platform_for_format(format_name),
            "confidence": item.get("confidence", 0) if isinstance(item, dict) else 0,
            "status": "draft",
        })
    return opportunities[:VIDEO_COUNT]


def run_pipeline():
    trends = get_trends()
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": DRY_RUN,
        "trend_count": len(trends),
        "opportunities": build_opportunities(trends),
    }
