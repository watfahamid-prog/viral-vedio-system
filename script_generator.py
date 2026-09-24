import json
import requests
from config import OPENAI_API_KEY, AI_MODE

def _fallback(trend, hook):
    return {
        "title": hook,
        "hook": hook,
        "script": f"Here is what is happening with {trend}. Follow for more quick updates.",
        "scenes": [hook, f"Here is what is happening with {trend}.", "Follow for more quick updates."],
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
Return ONLY valid JSON with keys: title, hook, script, scenes.
scenes must contain exactly 3 short visual/text scene descriptions."""

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={"model": "gpt-5.6-luna", "input": prompt, "max_output_tokens": 500},
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
