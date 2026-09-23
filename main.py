import json
from pipeline import run_pipeline
from video import create_video
from script_generator import generate_script
from publish import publish
from discord import notify

def main():
    result = run_pipeline()
    if result["opportunities"]:
        opportunity = result["opportunities"][0]
        script = generate_script(opportunity["trend"], opportunity["hook"])
        video_path = create_video(opportunity, script)
        result["video"] = video_path
        result["publishing"] = publish(video_path)
        notify(f"Viral scanner created a new original short: {script.get('title', opportunity['trend'])}")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
