import os
import time
from pathlib import Path

AI_VIDEO_ENABLED = os.getenv("AI_VIDEO_ENABLED", "true").lower() == "true"
HF_TOKEN = os.getenv("HF_TOKEN", "")
VIDEO_ENGINE = os.getenv("VIDEO_ENGINE", "auto").lower()
AI_VIDEO_MODEL = os.getenv("AI_VIDEO_MODEL", "Lightricks/LTX-Video-0.9.8-13B-distilled")
AI_VIDEO_PROVIDER = os.getenv("AI_VIDEO_PROVIDER", "fal-ai")
AI_VIDEO_TIMEOUT = int(os.getenv("AI_VIDEO_TIMEOUT", "180"))

def engine_available():
    if not AI_VIDEO_ENABLED or not HF_TOKEN:
        return False
    return VIDEO_ENGINE in {"auto", "hf", "hf_ltx", "hf_wan"}

def selected_model():
    if VIDEO_ENGINE == "hf_wan":
        return "Wan-AI/Wan2.1-T2V-1.3B"
    return AI_VIDEO_MODEL

def generate_clip(prompt, output_path, duration=5):
    """Generate one short AI clip through Hugging Face Inference Providers.

    This is deliberately clip-based: several short clips are safer and more
    controllable than asking a model for a whole 60-90 second video.
    """
    if not engine_available():
        return None
    try:
        from huggingface_hub import InferenceClient
        client = InferenceClient(provider=AI_VIDEO_PROVIDER, api_key=HF_TOKEN)
        video = client.text_to_video(
            prompt,
            model=selected_model(),
        )
        data = video if isinstance(video, (bytes, bytearray)) else bytes(video)
        if not data:
            return None
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if path.stat().st_size < 10_000:
            path.unlink(missing_ok=True)
            return None
        return str(path)
    except Exception as error:
        print(f"AI video engine unavailable: {error}")
        return None
