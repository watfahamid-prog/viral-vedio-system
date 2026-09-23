from datetime import datetime, timezone
from config import DRY_RUN, MAX_TRENDS, VIDEO_COUNT
from trends import get_trends


def build_opportunities(trends):
    opportunities = []
    for trend in trends[:MAX_TRENDS]:
        opportunities.append({
            "trend": trend,
            "hook": f"What you need to know about {trend}",
            "format": "short_explainer",
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
