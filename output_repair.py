import json
import os
import subprocess
from pathlib import Path


def _speech_text(script_data):
    text = str(script_data.get("script", "")).strip()
    if not text:
        text = " ".join(str(x) for x in script_data.get("scenes", []))
    return " ".join(text.split())


def _make_espeak_audio(script_data, work_dir, duration):
    speech = _speech_text(script_data)
    if not speech:
        return None
    voice = Path(work_dir) / "fallback_voice.wav"
    try:
        subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", "170", "-p", "48", "-a", "155",
             "-w", str(voice), speech],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return voice
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def repair_video(video_path, manifest_path, script_data, duration):
    """Make the inspection build self-healing when an optional TTS provider fails."""
    video = Path(video_path)
    manifest = Path(manifest_path)
    if not video.exists():
        return {"audio_repaired": False, "manifest_repaired": False}

    work = video.parent / ".repair"
    work.mkdir(exist_ok=True)
    audio = _make_espeak_audio(script_data, work, duration)
    audio_repaired = False

    if audio and audio.exists():
        repaired = work / "with_audio.mp4"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
                 "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                 "-t", str(duration), "-movflags", "+faststart", str(repaired)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            os.replace(repaired, video)
            audio_repaired = True
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    manifest_repaired = False
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            scenes = data.get("script", {}).get("scenes", [])
            data["scene_count"] = len(scenes) if scenes else data.get("scene_count", 0)
            data["audio"] = bool(audio_repaired or data.get("audio", False))
            data["audio_engine"] = "espeak-ng-fallback" if audio_repaired else data.get("audio_engine", "none")
            manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest_repaired = True
        except (OSError, json.JSONDecodeError):
            pass

    for p in work.glob("*"):
        try:
            p.unlink()
        except OSError:
            pass
    try:
        work.rmdir()
    except OSError:
        pass

    return {"audio_repaired": audio_repaired, "manifest_repaired": manifest_repaired}
