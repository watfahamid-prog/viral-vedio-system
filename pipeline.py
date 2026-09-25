from datetime import datetime, timezone
from config import DRY_RUN, MAX_TRENDS, VIDEO_COUNT
from trends import get_trends


def _category(text):
    value = str(text).lower()
    if any(w in value for w in ["football", "soccer", "match", "goal", "sport", "league", "nba", "nfl", "fifa"]):
        return "sports"
    if any(w in value for w in ["iphone", "android", "ai", "tech", "app", "google", "microsoft", "openai", "robot"]):
        return "technology"
    if any(w in value for w in ["movie", "film", "series", "actor", "music", "song", "celebrity", "show"]):
        return "entertainment"
    if any(w in value for w in ["election", "government", "minister", "president", "parliament"]):
        return "politics"
    return "general"


def _format_for_run(index, source, category="general", trend=""):
    """Choose a format from the topic instead of cycling blindly."""
    category = str(category).lower()
    source = str(source).lower()
    if category == "sports":
        choices = ["youtube_ranked_breakdown", "tiktok_cantina_story"]
    elif category == "entertainment":
        choices = ["tiktok_cantina_story", "short_explainer"]
    elif category == "technology":
        choices = ["youtube_quick_explainer", "short_explainer"]
    elif category == "politics":
        choices = ["youtube_quick_explainer", "short_explainer"]
    else:
        choices = ["short_explainer", "youtube_quick_explainer", "tiktok_cantina_story"]
    if "tiktok" in source and "tiktok_cantina_story" in choices:
        return "tiktok_cantina_story"
    return choices[(index + len(str(trend))) % len(choices)]


def _platform_for_format(format_name):
    if format_name.startswith("youtube_"):
        return "youtube"
    if format_name.startswith("tiktok_"):
        return "tiktok"
    return "shorts"


def build_opportunities(trends):
    hooks = {
        "youtube_ranked_breakdown": "Three quick things to know about {trend}.",
        "tiktok_cantina_story": "Wait — here is why {trend} is suddenly everywhere.",
        "youtube_quick_explainer": "Here is the simple explanation behind {trend}.",
        "short_explainer": "Here is the quick breakdown of {trend}.",
    }
    opportunities = []
    for index, item in enumerate(trends[:MAX_TRENDS]):
        trend = item["trend"] if isinstance(item, dict) else item
        source = item.get("source", "unknown") if isinstance(item, dict) else "unknown"
        category = _category(trend)
        format_name = _format_for_run(index, source, category, trend)
        opportunities.append({
            "trend": trend,
            "source": source,
            "sources": item.get("sources", [source]) if isinstance(item, dict) else [source],
            "score": item.get("score", 0) if isinstance(item, dict) else 0,
            "metrics": item.get("metrics", {}) if isinstance(item, dict) else {},
            "category": category,
            "hook": hooks[format_name].format(trend=trend),
            "format": format_name,
            "platform": _platform_for_format(format_name),
            "confidence": item.get("confidence", 0) if isinstance(item, dict) else 0,
            "status": "draft",
        })
    return opportunities[:VIDEO_COUNT]


def run_pipeline():
    trends = get_trends()
    opportunities = build_opportunities(trends)
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": DRY_RUN,
        "trend_count": len(trends),
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
    }
