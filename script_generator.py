import hashlib
import json
import requests
from config import OPENAI_API_KEY, AI_MODE


def _pick(options, seed):
    return options[int(seed, 16) % len(options)]


def _fallback(trend, hook):
    seed = hashlib.sha256(trend.encode("utf-8")).hexdigest()

    openers = [
        "Stop scrolling — this is the part people are talking about.",
        "This trend is moving fast, and here is the key detail.",
        "You have probably seen this everywhere. Here is the quick version.",
        "Here is the 15-second breakdown of what is happening.",
    ]
    bridges = [
        "The main thing to know is that this is getting attention right now.",
        "The reason it stands out is how quickly people are reacting to it.",
        "In simple terms, this is the detail worth watching.",
        "The interesting part is what happens next.",
    ]
    endings = [
        "Follow for more fast trend breakdowns.",
        "Save this and follow for the next update.",
        "Want more quick explainers? Follow for more.",
        "Check back for the next trend before it blows up.",
    ]

    opening = _pick(openers, seed[:8])
    bridge = _pick(bridges, seed[8:16])
    ending = _pick(endings, seed[16:24])

    title = trend.strip().title()
    if len(title) > 52:
        title = title[:49].rstrip() + "..."

    scenes = [
        f"HOOK: {hook}",
        f"CONTEXT: {trend} — {bridge}",
        f"TAKEAWAY: {ending}",
    ]

    return {
        "title": title,
        "hook": hook,
        "script": f"{opening} {hook} {bridge} {ending}",
        "scenes": scenes,
        "caption": f"{title} — quick breakdown.",
        "hashtags": ["#trending", "#shorts", "#viral"],
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
