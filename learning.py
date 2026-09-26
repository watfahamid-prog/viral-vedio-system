import json
import os
from collections import Counter
from datetime import datetime, timezone

STATE_FILE = "learning_state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "version": 1,
            "runs": 0,
            "videos": 0,
            "qc_failures": {},
            "platforms": {},
            "formats": {},
            "lessons": [],
        "creative_history": [],
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"version": 2, "runs": 0, "videos": 0, "qc_failures": {}, "platforms": {}, "formats": {}, "lessons": [], "creative_history": []}


def record_learning(result, qc_result):
    state = load_state()
    state["runs"] = state.get("runs", 0) + 1
    state["videos"] = state.get("videos", 0) + len(result.get("videos", []))

    failures = Counter()
    for item in qc_result.get("results", []):
        for error in item.get("errors", []):
            failures[error] += 1
        platform = item.get("platform", "unknown")
        state.setdefault("platforms", {}).setdefault(platform, {"checked": 0, "passed": 0})
        state["platforms"][platform]["checked"] += 1
        if item.get("passed"):
            state["platforms"][platform]["passed"] += 1

    for video in result.get("videos", []):
        fmt = video.get("format", "unknown")
        state.setdefault("formats", {}).setdefault(fmt, {"created": 0})
        state["formats"][fmt]["created"] += 1

    for key, count in failures.items():
        state.setdefault("qc_failures", {})[key] = state["qc_failures"].get(key, 0) + count

    lessons = []
    if failures.get("missing_audio"):
        lessons.append("Always keep a verified audio stream before notification.")
    if failures.get("wrong_vertical_resolution"):
        lessons.append("Render every platform asset at 1080x1920.")
    if failures.get("too_long"):
        lessons.append("Keep short-form videos inside the configured duration target.")
    if failures.get("file_too_small"):
        lessons.append("Reject tiny/corrupt outputs before they reach Discord.")
    if failures.get("shot_count_out_of_range"):
        lessons.append("Keep every short-form video between 4 and 11 distinct shots.")
    if failures.get("originality_flag_missing"):
        lessons.append("Require an explicit original-content flag before publishing.")

    for lesson in lessons:
        if lesson not in state.setdefault("lessons", []):
            state["lessons"].append(lesson)

    state["lessons"] = state["lessons"][-20:]
    state["last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return state


def learning_context():
    state = load_state()
    lessons = state.get("lessons", [])
    failures = state.get("qc_failures", {})
    if not lessons and not failures:
        return "No previous QC lessons yet. Experiment with varied hooks, pacing, visuals, and platform-specific formats."
    top = sorted(failures.items(), key=lambda x: x[1], reverse=True)[:5]
    return "Previous system lessons: " + "; ".join(lessons[-5:] or ["none"]) + ". Recent QC failure counts: " + ", ".join(f"{k}={v}" for k, v in top) + "."


def save_learning_summary(state, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "learning_summary.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
