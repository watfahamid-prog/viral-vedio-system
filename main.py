import json
from pipeline import run_pipeline
from discord import notify
from video import create_placeholder_video
from publish import publish


def main():
    result = run_pipeline()
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result["opportunities"]:
        opportunity = result["opportunities"][0]
        video_path = create_placeholder_video(opportunity)
        result["video"] = video_path
        result["publishing"] = publish(video_path)

    trends = [item["trend"] for item in result["opportunities"]]
    message = "🚀 Viral Video System scan complete.\\nFound {} trend topics.\\n{}".format(
        result["trend_count"], "\\n".join("• " + t for t in trends[:5])
    )
    try:
        if notify(message):
            print("📨 Discord notification sent.")
    except Exception as error:
        print(f"Discord notification failed: {error}")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
