from datetime import datetime, timezone
from config import DRY_RUN, MAX_TRENDS, VIDEO_COUNT
from trends import get_trends


def build_opportunities(trends):
    opportunities = []
    for item in trends[:MAX_TRENDS]:
        trend = item["trend"] if isinstance(item, dict) else item
        source = item.get("source", "unknown") if isinstance(item, dict) else "unknown"
        formats = {"youtube": "fast_breakdown", "tiktok": "commentary", "google": "news_explainer", "unknown": "quick_explainer"}
        hooks = {
            "youtube": f"This is trending on YouTube right now: {trend}",
            "tiktok": f"People are talking about {trend} right now.",
            "google": f"Here is the quick update on {trend}.",
            "unknown": f"Here is the quick breakdown of {trend}.",
        }
        opportunities.append({
            "trend": trend,
            "source": source,
            "hook": hooks.get(source, hooks["unknown"]),
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
