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
    if any(w in lower for w in ["election", "government", "minister", "president", "parliament"]):
        return "politics"
    return "general"


def _short_title(trend):
    words = re.sub(r"\s+", " ", trend.strip()).split()
    title = " ".join(words[:10]).title()
    return title if len(title) <= 58 else title[:55].rstrip() + "..."


def _clean(text):
    return re.sub(r"\s+", " ", re.sub(r"^(HOOK|WHY IT MATTERS|TAKEAWAY|SCENE \d+):\s*", "", str(text))).strip()


def _fallback(trend, hook, format_name="short_explainer"):
    seed = hashlib.sha256((trend + "|" + format_name).encode("utf-8")).hexdigest()
    category = _category(trend)
    clean_hook = _clean(hook)
    title = _short_title(trend)

    if format_name == "youtube_ranked_breakdown":
        title = f"3 Things About {title}"
        openings = [
            "Here are three quick things worth knowing.",
            "Let's break this down in three fast points.",
            "Three details explain why this is getting attention.",
        ]
        scenes = [
            clean_hook,
            "First: the trend itself is driving the conversation.",
            "Second: the reaction is helping it spread quickly.",
            "Third: the next development is what people will be watching.",
            "That is the quick breakdown. Follow for the next one.",
        ]
        hashtags = ["#shorts", "#trending", "#top3", "#explainer"]
    elif format_name == "tiktok_cantina_story":
        openings = [
            "Okay, this one moved fast.",
            "Wait — this is getting interesting.",
            "This trend suddenly started showing up everywhere.",
        ]
        scenes = [
            clean_hook,
            "At first, it looked like just another topic.",
            "Then the reactions started stacking up.",
            "Now people are watching to see what happens next.",
            "Follow for another fast story breakdown.",
        ]
        hashtags = ["#fyp", "#tiktok", "#trending", "#storytime"]
    elif format_name == "youtube_quick_explainer":
        openings = [
            "Here is the simple version.",
            "Let's make this easy to understand.",
            "Here is what this trend is about in a few seconds.",
        ]
        scenes = [
            clean_hook,
            f"The topic is getting attention in the {category} space.",
            "The important part is the change or reaction behind the headline.",
            "The conversation is still developing, so the next update matters.",
            "That is the short version. Follow for more explainers.",
        ]
        hashtags = ["#shorts", "#explained", "#trending", "#news"]
    else:
        openings = [
            "Here is the quick breakdown.",
            "This is the part you need to know.",
            "Here is why people are talking about this.",
        ]
        scenes = [
            clean_hook,
            "The first thing to understand is why the topic suddenly matters.",
            "The reaction is helping the story move beyond its original audience.",
            "More context will become clear as the story develops.",
            "Follow for more quick trend breakdowns.",
        ]
        hashtags = ["#trending", "#shorts", "#explainer"]

    opening = _pick(openings, seed[:8])
    script = " ".join([opening] + scenes)
    return {
        "title": title,
        "hook": clean_hook,
        "script": script,
        "scenes": scenes,
        "word_count": len(script.split()),
        "caption": f"{title} — original {format_name.replace('_', ' ')}.",
        "hashtags": hashtags,
        "format": format_name,
        "generation_mode": "template",
    }


def generate_script(trend: str, hook: str, format_name: str = "short_explainer") -> dict:
    if AI_MODE != "openai" or not OPENAI_API_KEY:
        return _fallback(trend, hook, format_name)

    prompt = f"""Create an original 15-second vertical short about this current topic.
TREND: {trend}
FORMAT: {format_name}
HOOK: {hook}

Use only information contained in the topic and hook. Do not invent names, numbers, quotes,
events, or causes. Do not copy any creator's wording, footage, watermark, or script.
Make it natural, fast, and easy to speak aloud. Target 35-50 spoken words.
Return ONLY valid JSON with keys: title, hook, script, scenes, caption, hashtags.
scenes must contain exactly 5 short visual/text scene descriptions.
hashtags must contain 3-5 short hashtags."""

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={"model": "gpt-5.6-luna", "input": prompt, "max_output_tokens": 700},
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
    result["format"] = format_name
    result["generation_mode"] = "openai"
    return result
