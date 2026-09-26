from datetime import datetime, timezone
import re
from difflib import SequenceMatcher
from config import DRY_RUN, MAX_TRENDS, VIDEO_COUNT
from trends import get_trends
from learning import load_state
from gemini_director import originality_review


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
    category = str(category).lower()
    source = str(source).lower()
    state = load_state()
    avoid_story = state.get("qc_failures", {}).get("too_long", 0) > 1
    if category == "sports":
        choices = ["youtube_real_commentary", "tiktok_cantina_story"]
    elif category == "entertainment":
        choices = ["tiktok_cantina_story", "short_explainer"]
    elif category == "technology":
        choices = ["youtube_real_commentary", "short_explainer"]
    elif category == "politics":
        choices = ["youtube_real_commentary", "short_explainer"]
    else:
        choices = ["youtube_real_commentary", "short_explainer", "tiktok_cantina_story"]
    if "tiktok" in source and "tiktok_cantina_story" in choices and not avoid_story:
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
        "youtube_real_commentary": "Top 10 real-life moments connected to {trend}.",
        "youtube_top10": "Top 10 {trend} moments you need to see.",
        "tiktok_cantina_story": "Wait — here is why {trend} is suddenly everywhere.",
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
    state = load_state()
    history = state.get("creative_history", [])
    candidates = []
    for item in opportunities:
        current = " ".join([item.get("trend",""), item.get("hook",""), item.get("format","")]).lower()
        best = 0.0
        for old in history[-100:]:
            previous = " ".join([old.get("trend",""), old.get("hook",""), old.get("format","")]).lower()
            if current and previous:
                best = max(best, SequenceMatcher(None, current, previous).ratio())
        item["originality_score"] = round(1.0 - best, 3)
        if best < 0.72:
            candidates.append(item)
    if not candidates and opportunities:
        candidates = [opportunities[0]]
    ai_keep = originality_review(candidates, history)
    if ai_keep is not None:
        candidates = [item for i, item in enumerate(candidates) if i in ai_keep]
    selected = candidates[:VIDEO_COUNT]

    # The primary pipeline must always produce VIDEO_COUNT normal videos.
    # YouTube Top-10 listicles are generated separately so a missing/weak
    # trend cannot accidentally reduce the total output count.
    fallback_topics = [
        "funniest moments caught on camera",
        "scariest moments caught on camera",
        "wildest unexpected moments",
    ]
    existing = {str(item.get("trend", "")).strip().lower() for item in selected}
    fallback_index = 0
    while len(selected) < VIDEO_COUNT:
        topic = fallback_topics[fallback_index % len(fallback_topics)]
        fallback_index += 1
        if topic in existing:
            continue
        selected.append({
            "trend": topic,
            "source": "fallback",
            "sources": ["fallback"],
            "score": 0,
            "metrics": {},
            "summary": "Reliable evergreen fallback concept used when live trend opportunities are insufficient.",
            "source_url": "",
            "publisher": "",
            "category": "general",
            "hook": hooks["short_explainer"].format(trend=topic),
            "format": "short_explainer",
            "platform": "shorts",
            "confidence": 0.7,
            "status": "fallback",
            "originality_score": 1.0,
        })
        existing.add(topic)

    for item in selected:
        item["platform"] = "shorts"
        item["format"] = "short_explainer"
        item["hook"] = hooks["short_explainer"].format(trend=item["trend"])
    history = state.setdefault("creative_history", [])
    for item in selected:
        history.append({"trend": item.get("trend",""), "hook": item.get("hook",""), "format": item.get("format",""), "category": item.get("category",""), "platform": item.get("platform","")})
    state["creative_history"] = history[-100:]
    with open("learning_state.json", "w", encoding="utf-8") as f:
        import json
        json.dump(state, f, ensure_ascii=False, indent=2)
    print("Originality memory:", len(state["creative_history"]), "concepts")
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
