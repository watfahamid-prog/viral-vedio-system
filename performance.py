import json
import os
from datetime import datetime, timezone

from config import OUTPUT_DIR


def record_run(result):
    """Store local performance-ready metadata for future platform analytics."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "performance_log.json")
    history = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "videos": [
            {
                "trend": item.get("trend"),
                "video": item.get("video"),
                "publishing": item.get("publishing"),
            }
            for item in result.get("videos", [])
        ],
        "note": "Platform view/like/comment data will be added when publishing analytics APIs are connected.",
    })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history[-100:], f, ensure_ascii=False, indent=2)
