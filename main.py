import json
import os
from pipeline import run_pipeline
from video import create_video, write_manifest
from script_generator import generate_script
from publish import publish
from discord import notify
from config import OUTPUT_DIR, VIDEO_COUNT

def main():
    result = run_pipeline()
    result["videos"] = []

    for index, opportunity in enumerate(result["opportunities"][:VIDEO_COUNT], 1):
        script = generate_script(opportunity["trend"], opportunity["hook"])
        video_path = create_video(opportunity, script, index)
        manifest_path = write_manifest(opportunity, script, video_path)
        result["videos"].append({
            "trend": opportunity["trend"],
            "video": video_path,
            "manifest": manifest_path,
            "generation_mode": script.get("generation_mode", "template"),
            "publishing": publish(video_path),
        })
        notify(
            f"Viral video ready #{index}: {script.get('title', opportunity['trend'])}\n"
            f"Trend: {opportunity['trend']}\n"
            f"Mode: {script.get('generation_mode', 'template')}"
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "run_summary.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
