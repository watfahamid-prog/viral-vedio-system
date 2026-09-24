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


def build_opportunities(trends):
    formats = {"youtube": "fast_breakdown", "tiktok": "commentary", "google": "news_explainer", "unknown": "quick_explainer"}
    hooks = {
        "youtube": "This is trending on YouTube right now: {trend}",
        "tiktok": "People are talking about {trend} right now.",
        "google": "Here is the quick update on {trend}.",
        "unknown": "Here is the quick breakdown of {trend}.",
    }
    opportunities = []
    for item in trends[:MAX_TRENDS]:
        trend = item["trend"] if isinstance(item, dict) else item
        source = item.get("source", "unknown") if isinstance(item, dict) else "unknown"
        opportunities.append({
            "trend": trend,
            "source": source,
            "score": item.get("score", 0) if isinstance(item, dict) else 0,
            "sources": item.get("sources", [source]) if isinstance(item, dict) else [source],
            "metrics": item.get("metrics", {}) if isinstance(item, dict) else {},
            "category": _category(trend),
            "hook": hooks.get(source, hooks["unknown"]).format(trend=trend),
            "format": formats.get(source, formats["unknown"]),
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
