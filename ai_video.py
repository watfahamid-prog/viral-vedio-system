import os
import time
from pathlib import Path
import requests

AI_VIDEO_ENABLED = os.getenv("AI_VIDEO_ENABLED", "true").lower() == "true"
VIDEO_ENGINE = os.getenv("VIDEO_ENGINE", "auto").lower()
AI_VIDEO_MODEL = os.getenv("AI_VIDEO_MODEL", "gen4.5").strip()
AI_VIDEO_TIMEOUT = max(15, min(90, int(os.getenv("AI_VIDEO_TIMEOUT", "60"))))
AI_VIDEO_MAX_CLIPS = max(0, min(8, int(os.getenv("AI_VIDEO_MAX_CLIPS", "6"))))
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "").strip()
LUMA_API_KEY = os.getenv("LUMA_API_KEY", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
HF_PROVIDER = os.getenv("AI_VIDEO_PROVIDER", "fal-ai").strip()

# Open models that can be routed through Hugging Face/fal when available.
HF_VIDEO_MODELS = [
    "Wan-AI/Wan2.1-T2V-1.3B",
    "Lightricks/LTX-Video",
]


def engine_available():
    return AI_VIDEO_ENABLED and bool(RUNWAY_API_KEY or LUMA_API_KEY or HF_TOKEN)


def _scene_class(prompt):
    p = prompt.lower()
    if any(x in p for x in ("person", "people", "man ", "woman ", "child", "crowd", "running", "walking", "talking")):
        return "human_motion"
    if any(x in p for x in ("car", "vehicle", "motorcycle", "train", "plane", "sports", "ball", "explosion")):
        return "fast_motion"
    if any(x in p for x in ("ocean", "mountain", "city", "landscape", "forest", "sky", "architecture")):
        return "environment"
    if any(x in p for x in ("close-up", "macro", "detail", "hands", "object", "product")):
        return "detail"
    return "cinematic"


def selected_engine_order(prompt=""):
    kind = _scene_class(prompt)
    if VIDEO_ENGINE == "runway":
        return ["runway", "luma", "hf"]
    if VIDEO_ENGINE == "luma":
        return ["luma", "runway", "hf"]
    if VIDEO_ENGINE in {"hf", "hf_wan"}:
        return ["hf", "runway", "luma"]
    if VIDEO_ENGINE == "hf_ltx":
        return ["hf", "luma", "runway"]

    # Auto-routing deliberately varies engines by shot type.
    if kind == "human_motion":
        return ["runway", "luma", "hf"]
    if kind == "fast_motion":
        return ["luma", "runway", "hf"]
    if kind == "environment":
        return ["runway", "luma", "hf"]
    if kind == "detail":
        return ["luma", "runway", "hf"]
    return ["runway", "luma", "hf"]


def _download(url, output_path):
    response = requests.get(url, timeout=AI_VIDEO_TIMEOUT, stream=True)
    response.raise_for_status()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    if path.stat().st_size < 50_000:
        path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded video is suspiciously small")
    return str(path)


def _runway(prompt, output_path, duration=5):
    if not RUNWAY_API_KEY:
        return None
    try:
        from runwayml import RunwayML
        client = RunwayML(api_key=RUNWAY_API_KEY)
        task = client.image_to_video.create(
            model=AI_VIDEO_MODEL if AI_VIDEO_MODEL in {"gen4.5", "gen4_turbo"} else "gen4.5",
            prompt_text=prompt,
            ratio="720:1280",
            duration=max(2, min(10, int(duration))),
        ).wait_for_task_output()
        outputs = getattr(task, "output", None) or []
        if not outputs:
            raise RuntimeError("Runway returned no output URL")
        return _download(outputs[0], output_path)
    except Exception as error:
        print(f"Runway engine failed: {error}")
        return None


def _luma(prompt, output_path, duration=5):
    if not LUMA_API_KEY:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {LUMA_API_KEY}",
            "Content-Type": "application/json",
            "accept": "application/json",
        }
        payload = {
            "prompt": prompt,
            "model": "ray-2",
            "resolution": "720p",
            "duration": "5s" if duration <= 5 else "9s",
            "aspect_ratio": "9:16",
        }
        response = requests.post(
            "https://api.lumalabs.ai/dream-machine/v1/generations/video",
            headers=headers, json=payload, timeout=30,
        )
        response.raise_for_status()
        generation_id = response.json().get("id")
        if not generation_id:
            raise RuntimeError("Luma returned no generation id")
        deadline = time.time() + AI_VIDEO_TIMEOUT
        while time.time() < deadline:
            status = requests.get(
                f"https://api.lumalabs.ai/dream-machine/v1/generations/{generation_id}",
                headers=headers, timeout=30,
            )
            status.raise_for_status()
            data = status.json()
            state = data.get("state")
            if state == "completed":
                url = (data.get("assets") or {}).get("video")
                if not url:
                    raise RuntimeError("Luma completed without a video asset")
                return _download(url, output_path)
            if state == "failed":
                raise RuntimeError(data.get("failure_reason") or "Luma generation failed")
            time.sleep(5)
        raise TimeoutError("Luma generation timed out")
    except Exception as error:
        print(f"Luma engine failed: {error}")
        return None


def _hf(prompt, output_path, duration=5):
    if not HF_TOKEN:
        return None
    try:
        from huggingface_hub import InferenceClient
        client = InferenceClient(provider=HF_PROVIDER, api_key=HF_TOKEN, timeout=AI_VIDEO_TIMEOUT)

        preferred = []
        if VIDEO_ENGINE == "hf_ltx":
            preferred = ["Lightricks/LTX-Video", "Wan-AI/Wan2.1-T2V-1.3B"]
        elif AI_VIDEO_MODEL and AI_VIDEO_MODEL not in {"gen4.5", "gen4_turbo"}:
            preferred = [AI_VIDEO_MODEL, "Lightricks/LTX-Video", "Wan-AI/Wan2.1-T2V-1.3B"]
        else:
            preferred = HF_VIDEO_MODELS

        for model in dict.fromkeys(preferred):
            try:
                print(f"Trying HF video model: {model}")
                video = client.text_to_video(prompt, model=model)
                data = video if isinstance(video, (bytes, bytearray)) else bytes(video)
                if data and len(data) >= 10_000:
                    Path(output_path).write_bytes(data)
                    return str(output_path)
            except Exception as error:
                print(f"HF model {model} failed: {error}")
    except Exception as error:
        print(f"Hugging Face engine failed: {error}")
    return None


def generate_clip(prompt, output_path, duration=5, force_engine=None):
    if not engine_available():
        return None

    order = [force_engine] if force_engine else selected_engine_order(prompt)
    engines = {"runway": _runway, "luma": _luma, "hf": _hf}

    for name in order:
        if name not in engines:
            continue
        if name == "runway" and not RUNWAY_API_KEY:
            continue
        if name == "luma" and not LUMA_API_KEY:
            continue
        if name == "hf" and not HF_TOKEN:
            continue
        print(f"Trying AI video engine: {name} | scene={_scene_class(prompt)}")
        result = engines[name](prompt, output_path, duration)
        if result:
            print(f"AI video generated successfully with {name}")
            return result
    return None
