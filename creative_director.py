import json
import os
import requests

ENABLED = os.getenv("GEMINI_ENABLED", "true").lower() == "true"
KEY = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

def _clean_json(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"): lines = lines[1:]
        if lines and lines[-1].strip() == "```:": lines = lines[:-1]
        text = "\n".join(lines).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1]) if start >= 0 and end > start else None

def _call(prompt, timeout=60):
    if not (ENABLED and KEY): return None
    url = "https://generativelanguage.googleapis.com/v1beta/models/" + MODEL + ":generateContent"
    response = requests.post(url, headers={"x-goog-api-key": KEY, "Content-Type": "application/json"}, json={
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.75, "responseMimeType": "application/json"},
    }, timeout=timeout)
    if not response.ok: return None
    text = ""
    for candidate in response.json().get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []): text += part.get("text", "")
    return _clean_json(text)

def optimize_scene_plan(script, opportunity):
    scenes = [str(x).strip() for x in script.get("scenes", []) if str(x).strip()]
    visuals = [str(x).strip() for x in script.get("visual_scenes", []) if str(x).strip()]
    count = max(8, min(14, min(len(scenes), len(visuals)) if visuals else len(scenes)))
    if count < 8: return script
    prompt = """
You are the final shot designer for a premium 9:16 short-form video.
Create a coherent shot plan for this exact script. Do not rewrite facts. The goal is visual storytelling, not a slideshow.
Rules: 8-14 distinct shots; maintain a continuity bible for recurring subjects; every shot changes at least two of action, framing, camera movement, depth, environment detail, lighting, composition; use varied shot grammar (macro, close-up, medium, wide, over-shoulder, tracking, low/high angle, reveal); first two shots must be visually arresting; middle escalates; final delivers payoff; no generic blue gradients, text cards, fake UI, logos, watermarks or copied footage; avoid impossible physics, deformed faces/hands, duplicated people, random wardrobe changes or inconsistent geography; no readable text inside generated footage.
Each visual prompt must contain subject + action + setting + framing + camera + lighting + continuity. Return ONLY JSON with continuity_bible and shot_plan. Each shot_plan item must have scene_index, visual_prompt, shot_type, camera, action, continuity.
TOPIC: """ + str(opportunity.get("trend", "current topic")) + "\nFORMAT: " + str(opportunity.get("format", "short explainer")) + "\nTITLE: " + str(script.get("title", "")) + "\nHOOK: " + str(script.get("hook", "")) + "\nSCENES: " + json.dumps(scenes[:count], ensure_ascii=False) + "\nEXISTING VISUAL PROMPTS: " + json.dumps(visuals[:count], ensure_ascii=False)
    try:
        result = _call(prompt)
        plan = result.get("shot_plan", []) if isinstance(result, dict) else []
        if len(plan) < 8: return script
        prompts = [str(x.get("visual_prompt", "")).strip() for x in plan[:count] if str(x.get("visual_prompt", "")).strip()]
        if len(prompts) < 8: return script
        enriched = dict(script)
        enriched["visual_scenes"] = prompts[:count]
        enriched["shot_plan"] = plan[:count]
        enriched["continuity_bible"] = result.get("continuity_bible", {})
        enriched["creative_director"] = True
        enriched["creative_director_model"] = MODEL
        return enriched
    except Exception as error:
        print("Creative shot planner skipped:", error)
        return script

def repair_weak_shot(script, scene_index, review_reason):
    visuals = list(script.get("visual_scenes", []) or [])
    if not (0 <= scene_index < len(visuals)): return None
    prompt = "Create ONE replacement vertical-video shot prompt. Fix this QC problem: " + str(review_reason) + "\nOriginal: " + visuals[scene_index] + "\nContinuity bible: " + json.dumps(script.get("continuity_bible", {}), ensure_ascii=False) + "\nKeep the same fact and continuity, but use different framing, camera movement and action/depth. No text, logos, watermarks, gradients or impossible physics. Return JSON only: {\"visual_prompt\":\"...\"}"
    try:
        result = _call(prompt, timeout=45)
        return str((result or {}).get("visual_prompt", "")).strip() or None
    except Exception:
        return None
