import json
import requests
from config import OPENAI_API_KEY

def generate_script(trend: str, hook: str) -> dict:
    """Generate an original short-form script. It does not copy source creators."""
    if not OPENAI_API_KEY:
        return {
            "title": hook,
            "hook": hook,
            "script": f"Here is what is happening with {trend}. Follow for more quick updates.",
            "scenes": [hook, f"Here is what is happening with {trend}.", "Follow for more quick updates."],
        }

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
    response.raise_for_status()
    data = response.json()
    text = data.get("output_text", "")
    if not text:
        for item in data.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    text += part.get("text", "")
    return json.loads(text)
