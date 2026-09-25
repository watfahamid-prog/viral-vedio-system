import os
from pathlib import Path

AI_VIDEO_ENABLED = os.getenv("AI_VIDEO_ENABLED", "true").lower() == "true"
HF_TOKEN = os.getenv("HF_TOKEN", "")
VIDEO_ENGINE = os.getenv("VIDEO_ENGINE", "auto").lower()
AI_VIDEO_MODEL = os.getenv("AI_VIDEO_MODEL", "Wan-AI/Wan2.1-T2V-1.3B")
AI_VIDEO_PROVIDER = os.getenv("AI_VIDEO_PROVIDER", "fal-ai")
AI_VIDEO_TIMEOUT = int(os.getenv("AI_VIDEO_TIMEOUT", "180"))

# Hugging Face's current text-to-video provider docs list Wan2.1-T2V-1.3B
# as a working text-to-video example. Keep LTX as a fallback only when a
# provider reports it supports the requested task.
FALLBACK_MODELS = [
    "Wan-AI/Wan2.1-T2V-1.3B",
    "tencent/HunyuanVideo",
    "Lightricks/LTX-Video",
]


def engine_available():
    return bool(
        AI_VIDEO_ENABLED
        and HF_TOKEN
        and VIDEO_ENGINE in {"auto", "hf", "hf_wan", "hf_ltx"}
    )


def selected_models():
    if VIDEO_ENGINE == "hf_ltx":
        requested = AI_VIDEO_MODEL or "Lightricks/LTX-Video"
        return [requested] + [m for m in FALLBACK_MODELS if m != requested]
    if VIDEO_ENGINE == "hf_wan":
        return ["Wan-AI/Wan2.1-T2V-1.3B"]
    requested = AI_VIDEO_MODEL or "Wan-AI/Wan2.1-T2V-1.3B"
    return [requested] + [m for m in FALLBACK_MODELS if m != requested]


def selected_model():
    return selected_models()[0]


def generate_clip(prompt, output_path, duration=5):
    """Generate one short text-to-video clip through Hugging Face.

    Providers control the exact duration they return, so the editor later
    trims/loops clips to the target social-video duration.
    """
    if not engine_available():
        return None

    try:
        from huggingface_hub import InferenceClient

        client = InferenceClient(
            provider=AI_VIDEO_PROVIDER,
            api_key=HF_TOKEN,
            timeout=AI_VIDEO_TIMEOUT,
        )

        last_error = None
        for model in selected_models():
            try:
                print(f"Trying AI video model: {model}")
                video = client.text_to_video(prompt, model=model)
                data = video if isinstance(video, (bytes, bytearray)) else bytes(video)
                if not data:
                    raise RuntimeError("Provider returned an empty video.")
                path = Path(output_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                if path.stat().st_size < 10_000:
                    path.unlink(missing_ok=True)
                    raise RuntimeError("Provider returned a suspiciously small video.")
                print(f"AI video generated successfully with {model}")
                return str(path)
            except Exception as error:
                last_error = error
                print(f"Model {model} unavailable: {error}")

        print(f"AI video generation failed after all model fallbacks: {last_error}")
        return None
    except Exception as error:
        print(f"AI video engine unavailable: {error}")
        return None
