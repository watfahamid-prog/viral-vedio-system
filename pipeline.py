from datetime import datetime, timezone
import re
from config import DRY_RUN, MAX_TRENDS, VIDEO_COUNT
from trends import get_trends
from learning import load_state


def _category(text):
    value = re.sub(r"^(källor|sources)[:\s]+", "", str(text).lower())
    if any(w in value for w in ["football", "soccer", "match", "goal", "sport", "league", "nba", "nfl", "fifa", "liding", "loppet", "marathon", "running", "race"]):
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
    state = load_state()
    avoid_story = state.get('qc_failures', {}).get('too_long', 0) > 1
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
    if 'tiktok' in source and 'tiktok_cantina_story' in choices and not avoid_story:
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
            "summary": item.get("context", {}).get("summary", "") if isinstance(item, dict) else "",
            "source_url": item.get("context", {}).get("source_url", "") if isinstance(item, dict) else "",
            "publisher": item.get("context", {}).get("publisher", "") if isinstance(item, dict) else "",
            "category": category,
            "hook": hooks[format_name].format(trend=trend),
            "format": format_name,
            "platform": _platform_for_format(format_name),
            "confidence": item.get("confidence", 0) if isinstance(item, dict) else 0,
            "status": "draft",
        })
    selected = opportunities[:VIDEO_COUNT]
    if len(selected) >= 2:
        for i, item in enumerate(selected):
            if i % 2 == 0:
                item['platform'] = 'youtube'
                item['format'] = 'youtube_ranked_breakdown' if item['category'] == 'sports' else 'youtube_quick_explainer'
            else:
                item['platform'] = 'tiktok'
                item['format'] = 'tiktok_cantina_story'
            item['hook'] = hooks[item['format']].format(trend=item['trend'])
    return selected


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
