import base64
import os
import requests
from pathlib import Path

GEMINI_TTS_ENABLED = os.getenv("GEMINI_TTS_ENABLED", "true").lower() == "true"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts").strip()
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Kore").strip()

def gemini_tts(text, output_path):
    if not (GEMINI_TTS_ENABLED and GEMINI_API_KEY and text.strip()):
        return None
    try:
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json={
                "model": GEMINI_TTS_MODEL,
                "input": [{
                    "type": "user_input",
                    "content": [{
                        "type": "text",
                        "text": text,
                        "annotations": [{
                            "type": "speech_metadata",
                            "style": "natural, energetic, clear social-video narration with confident pacing"
                        }]
                    }]
                }],
                "response_format": {"type": "audio"},
                "generation_config": {"speech_config": [{"voice": GEMINI_TTS_VOICE}]},
            },
            timeout=60,
        )
        if not response.ok:
            print(f"Gemini TTS skipped: HTTP {response.status_code}")
            return None
        data = response.json()
        audio_b64 = None
        output_audio = data.get("output_audio") or {}
        if output_audio.get("data"):
            audio_b64 = output_audio["data"]
        if not audio_b64:
            for step in data.get("steps", []):
                for part in step.get("content", []):
                    if part.get("type") == "audio" and part.get("data"):
                        audio_b64 = part["data"]
        if not audio_b64:
            return None
        raw = base64.b64decode(audio_b64)
        if len(raw) < 5000:
            return None
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return str(path)
    except Exception as error:
        print(f"Gemini TTS skipped: {error}")
        return None
