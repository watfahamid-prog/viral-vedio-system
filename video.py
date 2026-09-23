from pathlib import Path
from config import OUTPUT_DIR, VIDEO_SECONDS


def create_placeholder_video(opportunity):
    """Create a safe placeholder manifest until a video provider is connected.

    This intentionally does not copy another creator's video. A real renderer can
    consume this manifest and create an original short from the trend.
    """
    output = Path(OUTPUT_DIR)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "latest_video.json"
    path.write_text(
        __import__("json").dumps({
            "duration_seconds": VIDEO_SECONDS,
            "trend": opportunity["trend"],
            "hook": opportunity["hook"],
            "format": opportunity["format"],
            "original_content": True,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path)
