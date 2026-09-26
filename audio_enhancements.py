import os
import subprocess
from pathlib import Path
import requests

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ELEVENLABS_ENABLED = os.getenv("ELEVENLABS_ENABLED", "true").lower() == "true"


def elevenlabs_tts(text, output_path):
    """Optional free-tier voice upgrade. Returns None and never breaks the pipeline."""
    if not (ELEVENLABS_ENABLED and ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID and text.strip()):
        return None
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        response = requests.post(
            url,
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": ELEVENLABS_MODEL,
                "voice_settings": {
                    "stability": 0.42,
                    "similarity_boost": 0.78,
                    "style": 0.28,
                    "use_speaker_boost": True,
                },
            },
            timeout=45,
        )
        response.raise_for_status()
        if len(response.content) < 5000:
            return None
        Path(output_path).write_bytes(response.content)
        return str(output_path)
    except Exception as error:
        print(f"ElevenLabs TTS skipped: {error}")
        return None


def elevenlabs_sfx(prompt, output_path, duration=2.0):
    """Optional free-tier sound-design pass; capped to short clips."""
    if not (ELEVENLABS_ENABLED and ELEVENLABS_API_KEY and prompt.strip()):
        return None
    try:
        response = requests.post(
            "https://api.elevenlabs.io/v1/sound-generation",
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": prompt,
                "duration_seconds": max(0.5, min(5.0, float(duration))),
                "prompt_influence": 0.45,
            },
            timeout=45,
        )
        response.raise_for_status()
        if len(response.content) < 3000:
            return None
        Path(output_path).write_bytes(response.content)
        return str(output_path)
    except Exception as error:
        print(f"ElevenLabs SFX skipped: {error}")
        return None


def make_local_transition_sfx(output_path, duration=0.22, direction="up"):
    """No-key fallback: creates a tiny cinematic whoosh entirely with FFmpeg."""
    freq = 520 if direction == "up" else 760
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"sine=frequency={freq}:duration={duration}",
            "-af",
            "afade=t=in:st=0:d=0.03,afade=t=out:st="
            f"{max(0, duration-0.06):.3f}:d=0.06,"
            "lowpass=f=2400,volume=0.055",
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
            str(output_path),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return str(output_path)
