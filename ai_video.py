import base64
import mimetypes
import os
import time
from pathlib import Path
import requests

AI_VIDEO_ENABLED = os.getenv("AI_VIDEO_ENABLED", "true").lower() == "true"
VIDEO_ENGINE = os.getenv("VIDEO_ENGINE", "auto").lower()
AI_VIDEO_MODEL = os.getenv("AI_VIDEO_MODEL", "gen4.5").strip()
AI_VIDEO_TIMEOUT = max(20, min(300, int(os.getenv("AI_VIDEO_TIMEOUT", "120"))))
AI_VIDEO_MAX_CLIPS = max(0, min(8, int(os.getenv("AI_VIDEO_MAX_CLIPS", "6"))))
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "").strip()
LUMA_API_KEY = os.getenv("LUMA_API_KEY", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
HF_PROVIDER = os.getenv("AI_VIDEO_PROVIDER", "fal-ai").strip()
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "").strip()

HF_VIDEO_MODELS = ["Wan-AI/Wan2.1-T2V-1.3B", "Lightricks/LTX-Video"]

def available_engines():
    if not AI_VIDEO_ENABLED:
        return []
    engines = []
    if POLLINATIONS_API_KEY:
        engines.append("pollinations")
    if RUNWAY_API_KEY:
        engines.append("runway")
    if LUMA_API_KEY:
        engines.append("luma")
    if HF_TOKEN:
        engines.append("hf")
    return engines

def engine_available():
    return bool(available_engines())

def _scene_class(prompt):
    p = prompt.lower()
    if any(x in p for x in ("person", "people", "man ", "woman ", "child", "crowd", "running", "walking", "talking")): return "human_motion"
    if any(x in p for x in ("car", "vehicle", "motorcycle", "train", "plane", "sports", "ball", "explosion")): return "fast_motion"
    if any(x in p for x in ("ocean", "mountain", "city", "landscape", "forest", "sky", "architecture")): return "environment"
    if any(x in p for x in ("close-up", "macro", "detail", "hands", "object", "product")): return "detail"
    return "cinematic"

def selected_engine_order(prompt=""):
    if VIDEO_ENGINE == "pollinations": return ["pollinations", "hf", "runway", "luma"]
    if VIDEO_ENGINE == "runway": return ["runway", "pollinations", "luma", "hf"]
    if VIDEO_ENGINE == "luma": return ["luma", "pollinations", "runway", "hf"]
    if VIDEO_ENGINE in {"hf", "hf_wan", "hf_ltx"}: return ["hf", "pollinations", "runway", "luma"]
    return ["pollinations", "hf", "runway", "luma"]

def _download(url, output_path):
    response = requests.get(url, timeout=AI_VIDEO_TIMEOUT, stream=True)
    response.raise_for_status()
    path = Path(output_path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk: f.write(chunk)
    if path.stat().st_size < 50_000:
        path.unlink(missing_ok=True); raise RuntimeError("Downloaded video is suspiciously small")
    return str(path)

def _image_data_uri(image_path):
    path = Path(image_path); mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

def _pollinations(prompt, output_path, duration=4, image_path=None):
    if not POLLINATIONS_API_KEY: return None
    try:
        from media_engine import generate_video
        return generate_video(prompt, output_path, duration=duration)
    except Exception as error:
        print(f"Pollinations engine failed: {error}"); return None

def _runway(prompt, output_path, duration=5, image_path=None):
    if not RUNWAY_API_KEY: return None
    try:
        from runwayml import RunwayML
        client = RunwayML(api_key=RUNWAY_API_KEY)
        kwargs = {"model": AI_VIDEO_MODEL if AI_VIDEO_MODEL in {"gen4.5", "gen4_turbo"} else "gen4.5", "prompt_text": prompt, "ratio": "720:1280", "duration": max(2, min(10, int(duration)))}
        if image_path and Path(image_path).exists(): kwargs["prompt_image"] = _image_data_uri(image_path)
        task = client.image_to_video.create(**kwargs).wait_for_task_output()
        outputs = getattr(task, "output", None) or []
        return _download(outputs[0], output_path) if outputs else None
    except Exception as error:
        print(f"Runway engine failed: {error}"); return None

def _luma(prompt, output_path, duration=5, image_path=None):
    if not LUMA_API_KEY: return None
    try:
        headers={"Authorization":f"Bearer {LUMA_API_KEY}","Content-Type":"application/json","accept":"application/json"}
        payload={"prompt":prompt,"model":"ray-2","aspect_ratio":"9:16","resolution":"720p","duration":"5s" if duration<=5 else "9s"}
        response=requests.post("https://api.lumalabs.ai/dream-machine/v1/generations/video",headers=headers,json=payload,timeout=45); response.raise_for_status()
        generation_id=response.json().get("id"); deadline=time.time()+AI_VIDEO_TIMEOUT
        while generation_id and time.time()<deadline:
            data=requests.get(f"https://api.lumalabs.ai/dream-machine/v1/generations/{generation_id}",headers=headers,timeout=45).json()
            if data.get("state")=="completed": return _download((data.get("assets") or {}).get("video"),output_path)
            if data.get("state")=="failed": raise RuntimeError(data.get("failure_reason") or "Luma failed")
            time.sleep(5)
    except Exception as error: print(f"Luma engine failed: {error}")
    return None

def _hf(prompt, output_path, duration=5, image_path=None):
    if not HF_TOKEN: return None
    try:
        from huggingface_hub import InferenceClient
        client=InferenceClient(provider=HF_PROVIDER,api_key=HF_TOKEN,timeout=AI_VIDEO_TIMEOUT)
        preferred=[AI_VIDEO_MODEL,"Lightricks/LTX-Video","Wan-AI/Wan2.1-T2V-1.3B"] if AI_VIDEO_MODEL not in {"gen4.5","gen4_turbo"} else HF_VIDEO_MODELS
        for model in dict.fromkeys(preferred):
            try:
                video=client.text_to_video(prompt,model=model); data=video if isinstance(video,(bytes,bytearray)) else bytes(video)
                if data and len(data)>=10000: Path(output_path).write_bytes(data); return str(output_path)
            except Exception as error: print(f"HF model {model} failed: {error}")
    except Exception as error: print(f"Hugging Face engine failed: {error}")
    return None

def generate_clip(prompt, output_path, duration=5, image_path=None, force_engine=None):
    if not engine_available(): return None
    engines={"pollinations":_pollinations,"runway":_runway,"luma":_luma,"hf":_hf}
    order=[force_engine] if force_engine else selected_engine_order(prompt)
    for name in order:
        if name not in engines: continue
        if name=="pollinations" and not POLLINATIONS_API_KEY: continue
        if name=="runway" and not RUNWAY_API_KEY: continue
        if name=="luma" and not LUMA_API_KEY: continue
        if name=="hf" and not HF_TOKEN: continue
        print(f"Trying AI video engine: {name} | scene={_scene_class(prompt)}")
        result=engines[name](prompt,output_path,duration,image_path=image_path)
        if result: print(f"AI video generated successfully with {name}"); return result
    return None
