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
    if any(w in lower for w in ["football", "soccer", "match", "goal", "sport", "nba", "nfl", "fifa", "liding", "loppet", "marathon", "running", "race", "run"]):
        return "sports"
    if any(w in lower for w in ["iphone", "ai", "tech", "app", "google", "microsoft", "apple", "robot"]):
        return "technology"
    if any(w in lower for w in ["movie", "film", "series", "actor", "music", "song", "celebrity", "show"]):
        return "entertainment"
    if any(w in lower for w in ["election", "government", "minister", "president", "parliament", "trump", "iran", "ukraine", "russia"]):
        return "politics"
    return "general"


def _short_title(trend):
    words = re.sub(r"\s+", " ", trend.strip()).split()
    title = " ".join(words[:10]).title()
    return title if len(title) <= 58 else title[:55].rstrip() + "..."


def _clean(text):
    return re.sub(r"\s+", " ", re.sub(r"^(HOOK|WHY IT MATTERS|TAKEAWAY|SCENE \d+):\s*", "", str(text))).strip()


def _fallback(trend, hook, format_name="short_explainer", source_summary="", source_url=""):
    seed = hashlib.sha256((trend + "|" + format_name).encode("utf-8")).hexdigest()
    category = _category(trend)
    clean_hook = _clean(hook)
    title = _short_title(trend)
    topic_words = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", trend) if len(w) > 2]
    topic_phrase = " ".join(topic_words[:7]) or "this topic"
    evidence = _clean(re.sub(r"<[^>]+>", " ", source_summary))
    evidence = re.sub(r"&(?:nbsp|amp|quot|#39);", " ", evidence, flags=re.I)
    evidence = re.sub(r"\s+", " ", evidence).strip()
    evidence_sentences = [x.strip(" .") for x in re.split(r"(?<=[.!?])\s+", evidence) if len(x.strip()) > 20]
    evidence = ". ".join(evidence_sentences[:3])[:520]

    if format_name == "youtube_ranked_breakdown":
        title = f"3 Things About {title}"
        openings = ["Three things stand out here.", "Here is the fast version, without the fluff.", "Three details explain why this is getting attention."]
        scenes = [
            clean_hook,
            f"First: {topic_phrase} is gaining attention right now.",
            "Here is the key context behind the attention.",
            "The next detail explains what actually changed.",
            "Then the reaction shows why people noticed.",
            "The important part is what is confirmed so far.",
            "The next update is the detail worth watching.",
            "That is the quick breakdown.",
        ]
        hashtags = ["#shorts", "#trending", "#explainer", "#news"]
    elif format_name == "tiktok_cantina_story":
        openings = ["Okay, this moved fast.", "Wait — this one changed quickly.", "Here is the part that makes this interesting."]
        scenes = [
            clean_hook,
            "At first, it looked like just another update.",
            "Then one detail changed how people saw the story.",
            "The reaction made the story move even faster.",
            "Another detail explains what is happening now.",
            "The confirmed part is easier to understand than the headline.",
            "Now the question is what the next update shows.",
            "That is the story so far.",
        ]
        hashtags = ["#fyp", "#trending", "#story", "#explained"]
    elif format_name == "youtube_quick_explainer":
        openings = ["Here is the simple version.", "Let us make this easy to understand.", "Here is what matters in a few seconds."]
        scenes = [
            clean_hook,
            f"This is getting attention in the {category} space.",
            "Start with the actual change behind the headline.",
            "Then look at the detail that explains why it matters.",
            "The reaction adds another useful piece of context.",
            "What is confirmed is more important than speculation.",
            "The story can still develop from here.",
            "That is the short version.",
        ]
        hashtags = ["#shorts", "#explained", "#trending", "#news"]
    else:
        openings = ["Here is the quick breakdown.", "This is the part you need to know.", "Here is why this is getting attention."]
        scenes = [
            clean_hook,
            "First, understand what actually changed.",
            "Next, look at the detail behind the headline.",
            "Then look at the reaction and why people noticed.",
            "Another detail puts the story into context.",
            "Separate the confirmed facts from assumptions.",
            "Watch for the next confirmed update.",
            "That is the core of the story.",
        ]
        hashtags = ["#trending", "#shorts", "#explainer"]

    opening = _pick(openings, seed[:8])
    if evidence:
        evidence_lines = [
            f"The latest source describes it this way: {evidence[:150]}.",
            f"The source context adds: {evidence[150:300]}.",
            f"The remaining context says: {evidence[300:420]}.",
        ]
        scenes = [
            clean_hook,
            evidence_lines[0],
            "That gives the headline its immediate context.",
            evidence_lines[1] if evidence[150:300] else "The next detail is the part to watch.",
            "Keep the confirmed information separate from speculation.",
            evidence_lines[2] if evidence[300:420] else "The available source does not establish more than that.",
            "The story may change as more verified information appears.",
            "That is the verified short version from the available source.",
        ]
    visual_templates = {
        "sports": [
            f"Opening: wide stadium or competition establishing shot for {topic_phrase}, athletes moving through frame, fast push-in, dramatic natural light, deep background.",
            f"Action: close tracking shot of the relevant sporting action for {topic_phrase}, clear body movement, realistic motion blur, sideline perspective.",
            f"Detail: macro insert of ball, equipment or venue detail associated with {topic_phrase}, shallow depth, rack focus.",
            f"Reaction: crowd or team reaction after the key moment in {topic_phrase}, handheld documentary framing, realistic expressions.",
            f"Change: visually show the key turning point in {topic_phrase} with a before/after composition, lateral camera move, strong depth.",
            f"Context: alternate wide angle of the venue connected to {topic_phrase}, slow orbit, natural daylight, consistent setting.",
            f"Escalation: fast follow shot of the next decisive sporting movement, foreground obstruction, realistic physics and camera shake.",
            f"Payoff: clean hero shot of the venue/action tied to {topic_phrase}, slow pull-back, polished cinematic finish.",
        ],
        "technology": [
            f"Opening: cinematic close-up of a modern device or technology environment representing {topic_phrase}, screen glow without readable text, fast push-in.",
            f"Action: hands interacting naturally with the device or hardware behind {topic_phrase}, over-shoulder tracking shot, realistic reflections.",
            f"Detail: macro shot of a physical component associated with {topic_phrase}, controlled rack focus.",
            f"Reaction: user discovering the key feature behind {topic_phrase}, medium shot, natural indoor lighting, believable gesture.",
            f"Change: visual before/after demonstration of the technology's effect, lateral move, clear physical transformation.",
            f"Context: wider laboratory, office or home setting connected to {topic_phrase}, slow orbit, layered depth.",
            f"Escalation: dynamic close follow of the technology in use, foreground depth, realistic motion.",
            f"Payoff: premium technology environment hero shot representing {topic_phrase}, slow pull-back, clean finish.",
        ],
        "politics": [
            f"Opening: neutral cinematic exterior of the relevant government or civic setting for {topic_phrase}, slow push-in, natural daylight.",
            f"Context: officials or public participants moving through a formal civic environment, medium tracking shot, documentary lighting.",
            f"Detail: close-up of a document, microphone, podium or institutional detail relevant to {topic_phrase}, no readable text.",
            f"Reaction: neutral public or press reaction around the documented event, observational framing, realistic expressions.",
            f"Change: visual representation of the documented development in {topic_phrase}, controlled camera move, no persuasive symbolism.",
            f"Evidence: alternate exterior/interior angle of the relevant institution, steady camera, consistent geography.",
            f"Escalation: wider press or civic scene showing what happens next, natural movement, realistic depth.",
            f"Payoff: calm establishing shot returning to the relevant civic setting, slow pull-back, neutral documentary finish.",
        ],
        "general": [
            f"Opening: visually specific real-world establishing shot that represents {topic_phrase}, subject/action immediately clear, fast push-in, natural light.",
            f"Action: medium tracking shot showing the main physical action behind {topic_phrase}, realistic environment and layered depth.",
            f"Detail: macro close-up of a physical object or environmental detail that explains {topic_phrase}, rack focus.",
            f"Reaction: believable human or environmental reaction connected to {topic_phrase}, handheld documentary framing.",
            f"Change: clear visual before/after or transformation behind {topic_phrase}, dynamic camera move and realistic physics.",
            f"Context: alternate real location or angle that adds information about {topic_phrase}, slow orbit, consistent setting.",
            f"Escalation: follow shot showing what happens next around {topic_phrase}, stronger movement and foreground depth.",
            f"Payoff: memorable real-world hero shot directly tied to {topic_phrase}, decisive reveal or slow pull-back.",
        ],
    }
    visual_scenes = visual_templates.get(category, visual_templates["general"])
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


def generate_script(trend: str, hook: str, format_name: str = "short_explainer", source_summary: str = "", source_url: str = "") -> dict:
    if AI_MODE != "openai" or not OPENAI_API_KEY:
        return _fallback(trend, hook, format_name, source_summary, source_url)

    prompt = f"""Create an original vertical short about this current topic.
TREND: {trend}
FORMAT: {format_name}
HOOK: {hook}
SOURCE SUMMARY: {source_summary[:1800]}
SOURCE URL: {source_url}
PREVIOUS SYSTEM LESSONS: {learning_context()}

Use only information contained in the topic and hook. Do not invent names, numbers, quotes, events, or causes. Do not copy any creator's wording, footage, watermark, or script.
Make it natural, fast, specific, and easy to speak aloud. Use a strong first-second hook, escalating information, and a clean payoff. Avoid generic filler.
Target roughly 35-150 spoken words.
If the topic is political, describe documented information neutrally: do not persuade, endorse, attack, rank, or predict election outcomes.

Return ONLY valid JSON with keys: title, hook, script, scenes, visual_scenes, caption, hashtags.
scenes must contain exactly 8 short narration/caption lines with distinct information or visual purpose.
visual_scenes must contain exactly 8 production-ready visual directions. Each must specify visible subject/action, setting, camera movement, lighting, and continuity. Never request readable text, logos, watermarks, copied footage, or a recognizable creator's style.
The eight visual scenes must be meaningfully different so the finished short does not look like the same shot repeated.
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
        if len(result.get("scenes", [])) != 8 or len(result.get("visual_scenes", [])) != 8:
            raise ValueError("AI returned the wrong scene count")
        result["format"] = format_name
        result["learning_context_used"] = True
        result["generation_mode"] = "openai"
        return result
    except Exception as error:
        print(f"Invalid OpenAI script output, using fallback: {error}")
        return _fallback(trend, hook, format_name)
