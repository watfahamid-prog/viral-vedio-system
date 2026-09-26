import json
import os
import requests

GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "true").lower() == "true"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

def direct_script(trend, hook, format_name, source_summary, base_script):
    if not (GEMINI_ENABLED and GEMINI_API_KEY):
        return base_script
    prompt = ("You are a senior creative director for premium vertical short videos. "
              "Improve this draft without inventing facts. Make the hook immediate, narration natural and fast, "
              "and create 8-14 genuinely different scenes. Avoid repeated blue backgrounds, static cards, repeated "
              "camera moves, logos, watermarks and copied footage. Each visual scene must specify subject, action, "
              "setting, framing, camera movement, lighting and continuity. Build hook, setup, escalation, payoff. "
              "Return ONLY JSON with title, hook, script, scenes, visual_scenes, caption, hashtags. "
              "If political, stay neutral and factual.\n\nTOPIC: " + trend +
              "\nFORMAT: " + format_name + "\nHOOK: " + hook +
              "\nSOURCE: " + source_summary[:1800] +
              "\nDRAFT: " + json.dumps(base_script, ensure_ascii=False))
    url = "https://generativelanguage.googleapis.com/v1beta/models/" + GEMINI_MODEL + ":generateContent"
    try:
        response = requests.post(url, headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                                 json={"contents":[{"role":"user","parts":[{"text":prompt}]}],
                                       "generationConfig":{"temperature":0.9,"responseMimeType":"application/json"}}, timeout=60)
        if not response.ok:
            print("Gemini director skipped:", response.status_code)
            return base_script
        data = response.json()
        text = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text += part.get("text", "")
        start, end = text.find("{"), text.rfind("}")
        result = json.loads(text[start:end+1]) if start >= 0 and end > start else None
        if not result:
            return base_script
        scenes = [str(x).strip() for x in result.get("scenes", []) if str(x).strip()]
        visuals = [str(x).strip() for x in result.get("visual_scenes", []) if str(x).strip()]
        count = min(14, max(8, min(len(scenes), len(visuals))))
        if count < 8:
            return base_script
        result["scenes"] = scenes[:count]
        result["visual_scenes"] = visuals[:count]
        result["script"] = str(result.get("script") or " ".join(result["scenes"]))
        result["title"] = str(result.get("title") or base_script.get("title") or trend)
        result["hook"] = str(result.get("hook") or result["scenes"][0])
        result["caption"] = str(result.get("caption") or result["title"])
        result["hashtags"] = [str(x) for x in result.get("hashtags", [])][:5]
        result["generation_mode"] = str(base_script.get("generation_mode", "base")) + "+gemini_director"
        result["gemini_director"] = True
        return result
    except Exception as error:
        print("Gemini director skipped:", error)
        return base_script
