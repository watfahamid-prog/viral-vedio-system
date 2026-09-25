import hashlib
import json
import re
import requests
from config import OPENAI_API_KEY, OPENAI_MODEL, AI_MODE
from learning import learning_context


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
    topic_words = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", trend) if len(w) > 2]
    topic_phrase = " ".join(topic_words[:7]) or "this topic"

    if format_name == "youtube_ranked_breakdown":
        title = f"3 Things About {title}"
        openings = ["Three things stand out here.", "Here is the fast version, without the fluff.", "Three details explain why this is getting attention."]
        scenes = [
            clean_hook,
            f"First: {topic_phrase} is gaining attention right now.",
            "Second: the useful context is what changed, happened, or was reported.",
            "Third: the next confirmed update is the part worth watching.",
            "That is the quick breakdown.",
        ]
        hashtags = ["#shorts", "#trending", "#explainer", "#news"]
    elif format_name == "tiktok_cantina_story":
        openings = ["Okay, this moved fast.", "Wait — this one changed quickly.", "Here is the part that makes this interesting."]
        scenes = [
            clean_hook,
            "At first, it looked like just another update.",
            "Then the reactions started moving the story faster.",
            "Now the interesting part is what happens next.",
            "That is the story so far.",
        ]
        hashtags = ["#fyp", "#trending", "#story", "#explained"]
    elif format_name == "youtube_quick_explainer":
        openings = ["Here is the simple version.", "Let us make this easy to understand.", "Here is what matters in a few seconds."]
        scenes = [
            clean_hook,
            f"This is getting attention in the {category} space.",
            "The key point is the change or event behind the headline.",
            "The context matters because the story is still developing.",
            "That is the short version.",
        ]
        hashtags = ["#shorts", "#explained", "#trending", "#news"]
    else:
        openings = ["Here is the quick breakdown.", "This is the part you need to know.", "Here is why this is getting attention."]
        scenes = [
            clean_hook,
            "First, understand what actually changed.",
            "Next, look at the reaction and why people are paying attention.",
            "Then watch for the next confirmed update.",
            "That is the core of the story.",
        ]
        hashtags = ["#trending", "#shorts", "#explainer"]

    opening = _pick(openings, seed[:8])
    visual_scenes = [
        f"Opening: a striking real-world establishing shot that instantly communicates {topic_phrase}; the main subject enters frame, fast push-in camera, natural lighting, shallow depth of field.",
        f"Context: a close-up of the key subject or object connected to {topic_phrase} performing a clear action; handheld tracking, realistic motion, layered background.",
        f"Reaction: a visually surprising but plausible moment showing the human or environmental reaction around {topic_phrase}; quick camera move, expressive movement, cinematic contrast.",
        f"Detail: a different location or angle that explains the next important part of {topic_phrase}; smooth orbit or dolly movement, strong foreground/background separation.",
        f"Payoff: a memorable final visual tied directly to {topic_phrase}; camera pulls back or reveals the wider scene, energetic movement, polished cinematic finish.",
    ]
    script = " ".join([opening] + scenes)
    return {
        "title": title,
        "hook": clean_hook,
        "script": script,
        "scenes": scenes,
        "visual_scenes": visual_scenes,
        "word_count": len(script.split()),
        "caption": f"{title} — original {format_name.replace('_', ' ')}.",
        "hashtags": hashtags,
        "format": format_name,
        "generation_mode": "template",
    }


def generate_script(trend: str, hook: str, format_name: str = "short_explainer") -> dict:
    if AI_MODE != "openai" or not OPENAI_API_KEY:
        return _fallback(trend, hook, format_name)

    prompt = f"""Create an original vertical short about this current topic.
TREND: {trend}
FORMAT: {format_name}
HOOK: {hook}
PREVIOUS SYSTEM LESSONS: {learning_context()}

Use only information contained in the topic and hook. Do not invent names, numbers, quotes, events, or causes. Do not copy any creator's wording, footage, watermark, or script.
Make it natural, fast, specific, and easy to speak aloud. Use a strong first-second hook, escalating information, and a clean payoff. Avoid generic filler.
Target roughly 35-150 spoken words.
If the topic is political, describe documented information neutrally: do not persuade, endorse, attack, rank, or predict election outcomes.

Return ONLY valid JSON with keys: title, hook, script, scenes, visual_scenes, caption, hashtags.
scenes must contain exactly 5 short narration/caption lines with distinct information or visual purpose.
visual_scenes must contain exactly 5 production-ready visual directions. Each must specify visible subject/action, setting, camera movement, lighting, and continuity. Never request readable text, logos, watermarks, copied footage, or a recognizable creator's style.
The five visual scenes must be meaningfully different so the finished short does not look like the same shot repeated.
hashtags must contain 3-5 short hashtags."""

    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": OPENAI_MODEL, "input": prompt, "max_output_tokens": 900},
            timeout=60,
        )
    except requests.RequestException as error:
        print(f"OpenAI script generation failed, using template fallback: {error}")
        return _fallback(trend, hook, format_name)
    if response.status_code == 429:
        print("OpenAI API quota/rate limit reached; using template fallback.")
        return _fallback(trend, hook, format_name)
    if not response.ok:
        print(f"OpenAI API error {response.status_code}; using template fallback.")
        return _fallback(trend, hook, format_name)
    try:
        data = response.json()
        text = data.get("output_text", "")
        if not text:
            for item in data.get("output", []):
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text += part.get("text", "")
        result = json.loads(text)
        if len(result.get("scenes", [])) != 5 or len(result.get("visual_scenes", [])) != 5:
            raise ValueError("AI returned the wrong scene count")
        result["format"] = format_name
        result["learning_context_used"] = True
        result["generation_mode"] = "openai"
        return result
    except Exception as error:
        print(f"Invalid OpenAI script output, using fallback: {error}")
        return _fallback(trend, hook, format_name)
