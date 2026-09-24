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


def _fallback(trend, hook, format_name="short_explainer"):
    seed = hashlib.sha256((trend + format_name).encode("utf-8")).hexdigest()
    category = _category(trend)

    clean_hook = re.sub(r"^(HOOK|WHY IT MATTERS|TAKEAWAY):\s*", "", str(hook)).strip()
    base_title = _short_title(trend)

    if format_name == "youtube_ranked_breakdown":
        title = f"3 Things To Know: {base_title}"
        openers = [
            "Here are three things to know about this trend.",
            "Three quick points — then you can decide what matters.",
            "Let's break this trend down in three fast steps.",
        ]
        bridges = [
            "First, the trend itself is driving the conversation.",
            "Next, the reaction is what is pushing this story further.",
            "And the biggest question is what happens next.",
        ]
        ending = "Follow for the next ranked breakdown."
        hashtags = ["#shorts", "#trending", "#top3", "#viral"]
    elif format_name == "tiktok_cantina_story":
        title = base_title
        openers = [
            "Wait, you need to see what is happening here.",
            "Okay, this trend is moving fast.",
            "This is the part everyone is talking about.",
        ]
        bridges = [
            "The reaction is exactly why this keeps spreading.",
            "And this is where the story gets interesting.",
            "That is why people keep coming back to this trend.",
        ]
        ending = "Follow for the next story."
        hashtags = ["#fyp", "#tiktok", "#trending", "#viral"]
    else:
        title = base_title
        openers = [
            "Here is the quick breakdown.",
            "This is what people are watching right now.",
            "Here is the part you need to know.",
        ]
        bridges = {
            "sports": [
                "The key detail is the latest action and the reaction around it.",
                "What matters most is the moment changing the conversation.",
            ],
            "technology": [
                "The key detail is what changed and why people are paying attention.",
                "What stands out is the new idea or reaction around it.",
            ],
            "entertainment": [
                "The key detail is the reaction and why people keep talking about it.",
                "What stands out is the moment pushing this into the spotlight.",
            ],
            "general": [
                "The key detail is why this suddenly got so much attention.",
                "What stands out is how quickly people started reacting.",
            ],
        }[category]
        ending = "Follow for more quick trend breakdowns."
        hashtags = {
            "sports": ["#sports", "#football", "#shorts", "#trending"],
            "technology": ["#tech", "#ai", "#shorts", "#trending"],
            "entertainment": ["#entertainment", "#news", "#shorts", "#trending"],
            "general": ["#trending", "#news", "#shorts"],
        }[category]

    opening = _pick(openers, seed[:8])
    bridge = _pick(bridges, seed[8:16])

    scenes = [clean_hook, bridge, ending]
    script = f"{opening} {clean_hook} {bridge} {ending}"

    return {
        "title": title,
        "hook": clean_hook,
        "script": script,
        "scenes": scenes,
        "word_count": len(script.split()),
        "caption": f"{title} — {format_name.replace('_', ' ')}.",
        "hashtags": hashtags,
        "format": format_name,
        "generation_mode": "template",
    }


def generate_script(trend: str, hook: str, format_name: str = "short_explainer") -> dict:
    # Template mode is the default and works without OpenAI API credits.
    if AI_MODE != "openai":
        return _fallback(trend, hook, format_name)

    if not OPENAI_API_KEY:
        return _fallback(trend, hook, format_name)

    prompt = f"""Create an original 15-second vertical short about this trend.
TREND: {trend}
FORMAT: {format_name}
HOOK: {hook}
Do not copy any creator's wording, footage, watermark, or script.
Keep claims factual and avoid inventing details.
For youtube_ranked_breakdown, use a fast ranked/list-style structure without inventing facts.
For tiktok_cantina_story, use a fast conversational story/commentary structure.
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
    result["format"] = format_name
    result["generation_mode"] = "openai"
    return result
