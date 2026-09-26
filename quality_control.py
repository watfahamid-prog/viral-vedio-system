import json
import os
import subprocess
from pathlib import Path

from config import VIDEO_MAX_SECONDS, VIDEO_MIN_SECONDS


def _probe(video_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size",
        "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json", video_path,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "duration": float(fmt.get("duration", 0) or 0),
        "size": int(float(fmt.get("size", 0) or 0)),
        "width": int(video.get("width", 0) or 0),
        "height": int(video.get("height", 0) or 0),
        "video_codec": video.get("codec_name", ""),
        "audio_codec": audio.get("codec_name", ""),
        "has_audio": bool(audio),
    }


def check_video(video_path, platform="youtube", item_script=None):
    errors, warnings = [], []
    path = Path(video_path)
    if not path.exists():
        return {"passed": False, "errors": ["file_missing"], "warnings": [], "metrics": {}}

    try:
        metrics = _probe(str(path))
    except Exception as error:
        return {"passed": False, "errors": [f"ffprobe_failed:{error}"], "warnings": [], "metrics": {}}

    if metrics["size"] < 50_000:
        errors.append("file_too_small")
    if metrics["width"] != 1080 or metrics["height"] != 1920:
        errors.append("wrong_vertical_resolution")
    if not metrics["has_audio"]:
        errors.append("missing_audio")
    if metrics["duration"] < VIDEO_MIN_SECONDS:
        errors.append("too_short")
    if metrics["duration"] > min(VIDEO_MAX_SECONDS, 180):
        errors.append("too_long")


    # Visual integrity: reject a long full-black section.
    try:
        black = subprocess.run([
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-vf", "blackdetect=d=1.0:pix_th=0.10",
            "-an", "-f", "null", "-"
        ], capture_output=True, text=True, timeout=45)
        if "black_start:" in (black.stderr or ""):
            errors.append("long_black_section")
    except Exception:
        warnings.append("black_frame_check_unavailable")

    # Manifest and creative-structure checks.
    manifest = path.with_suffix('.json')
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding='utf-8'))
            shots = int(data.get('scene_count', 0) or 0)
            if shots < 8 or shots > 14:
                errors.append('scene_count_out_of_range')
            if not data.get('original_content', False):
                errors.append('originality_flag_missing')
        except Exception:
            warnings.append('manifest_unreadable')
    else:
        warnings.append('manifest_missing')

    # Optional Gemini frame-level creative review.
    try:
        from visual_qc import review_video
        visual = review_video(str(path), item_script if isinstance(item_script, dict) else {})
        if visual.get("enabled"):
            result_note = visual
        else:
            result_note = visual
    except Exception as error:
        result_note = {"enabled": False, "warning": str(error)}

    # Platform-specific checks.
    if platform == "tiktok" and metrics["duration"] > 60:
        warnings.append("tiktok_target_over_60_seconds")
    if platform == "youtube" and metrics["duration"] > 90:
        warnings.append("youtube_short_target_over_90_seconds")

    return {
        "passed": not errors and result_note.get("passed", True),
        "platform": platform,
        "errors": errors,
        "warnings": warnings + ([result_note.get("warning")] if result_note.get("warning") else []),
        "visual_review": result_note,
        "metrics": metrics,
    }


def quality_check(video_items):
    results = []
    for item in video_items:
        result = check_video(item["video"], item.get("platform", "youtube"), item.get("script", {}))
        result["video"] = item["video"]
        result["trend"] = item.get("trend")
        results.append(result)

    passed = sum(1 for x in results if x["passed"])
    return {
        "passed": passed == len(results) and bool(results),
        "passed_count": passed,
        "total_count": len(results),
        "results": results,
    }
