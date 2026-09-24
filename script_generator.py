import hashlib
import json
import re
import requests
from config import OPENAI_API_KEY, AI_MODE


def _pick(options, seed):
    return options[int(seed, 16) % len(options)]


def _category(trend):
    lower = trend.lower()
    if any(w in lower for w in ["football", "soccer", "match", "goal", "sport", "nba", "nfl", "fifa"]):
        return "sports"
    if any(w in lower for w in ["iphone", "ai", "tech", "app", "google", "microsoft", "apple", "robot"]):
        return "technology"
    if any(w in lower for w in ["movie", "film", "series", "actor", "music", "song", "celebrity", "show"]):
        return "entertainment"
    return "general"


def _short_title(trend):
    words = trend.strip().split()
    title = " ".join(words[:9]).title()
    return title if len(title) <= 52 else title[:49].rstrip() + "..."


def _fallback(trend, hook):
    seed = hashlib.sha256(trend.encode("utf-8")).hexdigest()
    category = _category(trend)

    openers = [
        "Here is the quick breakdown.",
        "This is what everyone is watching right now.",
        "Here is the part you need to know.",
        "This trend is getting attention fast.",
    ]
    bridges = {
        "sports": [
            "The key detail is the latest action and what it could mean next.",
            "The big talking point is the latest result and the reaction around it.",
            "What matters most is the moment that changed the conversation.",
        ],
        "technology": [
            "The key detail is what changed and why people are paying attention.",
            "What stands out is the new feature, idea, or reaction around it.",
            "The interesting part is how quickly this technology is getting attention.",
        ],
        "entertainment": [
            "The key detail is the reaction and why people keep talking about it.",
            "What stands out is the moment that pushed this story into the spotlight.",
            "The interesting part is how quickly the conversation is growing.",
        ],
        "general": [
            "The key detail is why this suddenly started getting so much attention.",
            "What stands out is how quickly people started reacting to it.",
            "The interesting part is what happens next as the trend keeps moving.",
        ],
    }
    endings = [
        "Follow for more quick trend breakdowns.",
        "Save this for the next update.",
        "Follow for the next trend.",
    ]

    opening = _pick(openers, seed[:8])
    bridge = _pick(bridges[category], seed[8:16])
    ending = _pick(endings, seed[16:24])

    clean_hook = re.sub(r"^(HOOK|WHY IT MATTERS|TAKEAWAY):\s*", "", str(hook)).strip()
    title = _short_title(trend)

    scenes = [
        clean_hook,
        bridge,
        ending,
    ]

    hashtags = {
        "sports": ["#sports", "#football", "#shorts", "#trending"],
        "technology": ["#tech", "#ai", "#shorts", "#trending"],
        "entertainment": ["#entertainment", "#news", "#shorts", "#trending"],
        "general": ["#trending", "#news", "#shorts"],
    }[category]

    script = f"{opening} {clean_hook} {bridge} {ending}"

    return {
        "title": title,
        "hook": clean_hook,
        "script": script,
        "scenes": scenes,
        "caption": f"{title} — quick breakdown.",
        "hashtags": hashtags,
        "generation_mode": "template",
    }


def generate_script(trend: str, hook: str) -> dict:
    # Template mode is the default and works without OpenAI API credits.
    if AI_MODE != "openai":
        return _fallback(trend, hook)

    if not OPENAI_API_KEY:
        return _fallback(trend, hook)

    prompt = f"""Create an original 15-second vertical short about this trend.
TREND: {trend}
HOOK: {hook}
Do not copy any creator's wording, footage, watermark, or script.
Keep claims factual and avoid inventing details.
Make the narration natural, punchy, and easy to speak aloud.
Target roughly 35-50 spoken words.
Return ONLY valid JSON with keys: title, hook, script, scenes, caption, hashtags.
scenes must contain exactly 3 short visual/text scene descriptions.
hashtags must contain 3-5 short hashtags."""

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-5.6-luna",
            "input": prompt,
            "max_output_tokens": 700,
        },
        timeout=60,
    )

    if response.status_code == 429:
        detail = response.json() if response.content else {}
        error = detail.get("error", {})
        raise RuntimeError(
            f"OpenAI API 429 ({error.get('code', 'rate_limit_or_quota')}): "
            f"{error.get('message', 'quota or rate limit reached')}"
        )

    response.raise_for_status()
    data = response.json()
    text = data.get("output_text", "")
    if not text:
        for item in data.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    text += part.get("text", "")

    result = json.loads(text)
    result["generation_mode"] = "openai"
    return result
