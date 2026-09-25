import os
import time
from pathlib import Path
import requests

AI_VIDEO_ENABLED = os.getenv("AI_VIDEO_ENABLED", "true").lower() == "true"
VIDEO_ENGINE = os.getenv("VIDEO_ENGINE", "auto").lower()
AI_VIDEO_MODEL = os.getenv("AI_VIDEO_MODEL", "gen4.5")
AI_VIDEO_TIMEOUT = int(os.getenv("AI_VIDEO_TIMEOUT", "180"))
AI_VIDEO_MAX_CLIPS = int(os.getenv("AI_VIDEO_MAX_CLIPS", "3"))
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "")
LUMA_API_KEY = os.getenv("LUMA_API_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_PROVIDER = os.getenv("AI_VIDEO_PROVIDER", "fal-ai")

FALLBACK_MODELS = [
    "Wan-AI/Wan2.1-T2V-1.3B",
    "Lightricks/LTX-Video",
]


def engine_available():
    if not AI_VIDEO_ENABLED:
        return False
    return bool(RUNWAY_API_KEY or LUMA_API_KEY or HF_TOKEN)


def selected_engine_order():
    if VIDEO_ENGINE == "runway":
        return ["runway", "luma", "hf"]
    if VIDEO_ENGINE == "luma":
        return ["luma", "runway", "hf"]
    if VIDEO_ENGINE in {"hf", "hf_wan", "hf_ltx"}:
        return ["hf", "runway", "luma"]
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
    if path.stat().st_size < 10_000:
        path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded video is suspiciously small")
    return str(path)


def _runway(prompt, output_path, duration=5):
    if not RUNWAY_API_KEY:
        return None
    try:
        from runwayml import RunwayML, TaskFailedError
        client = RunwayML(api_key=RUNWAY_API_KEY)
        task = client.image_to_video.create(
            model=AI_VIDEO_MODEL if AI_VIDEO_MODEL in {"gen4.5", "gen4_turbo"} else "gen4.5",
            prompt_text=prompt,
            ratio="768:1280",
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
        headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Content-Type": "application/json", "accept": "application/json"}
        payload = {
            "prompt": prompt,
            "model": "ray-2",
            "resolution": "720p",
            "duration": "5s" if duration <= 5 else "9s",
            "aspect_ratio": "9:16",
        }
        response = requests.post("https://api.lumalabs.ai/dream-machine/v1/generations/video", headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        generation = response.json()
        generation_id = generation.get("id")
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
        models = ["Wan-AI/Wan2.1-T2V-1.3B", "Lightricks/LTX-Video"]
        if VIDEO_ENGINE == "hf_ltx":
            models.reverse()
        for model in models:
            try:
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


def generate_clip(prompt, output_path, duration=5):
    if not engine_available():
        return None
    engines = {"runway": _runway, "luma": _luma, "hf": _hf}
    for name in selected_engine_order():
        if name == "runway" and not RUNWAY_API_KEY:
            continue
        if name == "luma" and not LUMA_API_KEY:
            continue
        if name == "hf" and not HF_TOKEN:
            continue
        print(f"Trying AI video engine: {name}")
        result = engines[name](prompt, output_path, duration)
        if result:
            print(f"AI video generated successfully with {name}")
            return result
    return None
