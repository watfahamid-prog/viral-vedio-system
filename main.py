import json
import os
from pipeline import run_pipeline
from video_v5 import create_video
from video_v4 import write_manifest
from script_generator import generate_script
from gemini_director import direct_script
from creative_director import optimize_scene_plan
from publish import publish
from discord import notify
from config import OUTPUT_DIR, VIDEO_COUNT
from performance import record_run
from self_test import main as run_self_test
from quality_control import quality_check
from learning import record_learning, save_learning_summary, learning_context, load_state
from trends import get_trends
from youtube_commentary import create_youtube_commentary_video


def main():
    run_mode = os.getenv("RUN_MODE", "both").strip().lower()
    # YouTube shards do not use the trend-opportunity pipeline. Running the
    # old self-test there incorrectly required 3 normal opportunities and
    # stopped every YouTube job before it could generate a video.
    if run_mode != "youtube":
        run_self_test()
    print("Learning context:", learning_context())
    if run_mode not in {"youtube", "normal", "both"}:
        raise RuntimeError(f"Invalid RUN_MODE: {run_mode}")
    print(f"RUN_MODE={run_mode}")

    # The YouTube lane uses fixed evergreen listicle topics and does not need
    # the expensive trend-scan stage. Normal videos still run the full scanner.
    if run_mode in {"normal", "both"}:
        result = run_pipeline()
    else:
        result = {
            "opportunities": [],
            "trend_count": 0,
            "videos": [],
        }
    result["videos"] = []

    if run_mode in {"normal", "both"} and not result["opportunities"]:
        raise RuntimeError("No trend opportunities were found. Nothing was generated.")

    # Normal videos are generated only in normal/both mode.
    if run_mode in {"normal", "both"}:
        requested_video_index = int(os.getenv("VIDEO_INDEX", "0") or "0")
        if requested_video_index in {1, 2, 3}:
            selected_opportunities = [(requested_video_index, result["opportunities"][requested_video_index - 1])]
        else:
            selected_opportunities = list(enumerate(result["opportunities"][:VIDEO_COUNT], 1))

        for index, opportunity in selected_opportunities:
            script = generate_script(
                opportunity["trend"],
                opportunity["hook"],
                opportunity.get("format", "short_explainer"),
                opportunity.get("summary", ""),
                opportunity.get("source_url", ""),
            )
            script = direct_script(
                opportunity["trend"],
                opportunity["hook"],
                opportunity.get("format", "short_explainer"),
                opportunity.get("summary", ""),
                script,
            )
            script = optimize_scene_plan(script, opportunity)
            video_path = create_video(opportunity, script, index)
            manifest_path = write_manifest(opportunity, script, video_path)

            if not os.path.exists(video_path) or os.path.getsize(video_path) < 50_000:
                raise RuntimeError(f"Output quality gate failed for video #{index}")
            if not os.path.exists(manifest_path):
                raise RuntimeError(f"Manifest quality gate failed for video #{index}")

            result["videos"].append({
                "trend": opportunity["trend"],
                "source": opportunity.get("source", "unknown"),
                "sources": opportunity.get("sources", []),
                "video": video_path,
                "manifest": manifest_path,
                "generation_mode": script.get("generation_mode", "template"),
                "platform": "shorts",
                "format": opportunity.get("format", "short_explainer"),
                "confidence": opportunity.get("confidence", 0),
                "script": script,
                "publishing": {"status": "pending_quality_control"},
            })

        expected_normal = len(selected_opportunities)
        if len(result["videos"]) != expected_normal:
            raise RuntimeError(
                f"Pipeline quality gate failed: expected exactly {expected_normal} normal video(s), "
                f"created {len(result['videos'])}"
            )

    # YouTube is a dedicated Top-10 entertainment lane. It uses fixed semantic
    # formats so the footage always matches the promised category.
    youtube_outputs = []
    youtube_candidates = []
    if run_mode in {"youtube", "both"}:
        # Do not let an arbitrary live topic such as "Iran" become the subject
        # of a funny listicle. The YouTube lane promises an entertainment format,
        # so the semantic theme is locked here.
        listicle_formats = [
            {"trend": "funniest moments caught on camera", "listicle_theme": "funniest",
             "angle": "fails and instant regrets"},
            {"trend": "funniest reactions caught on camera", "listicle_theme": "funniest",
             "angle": "unexpected reactions and perfect timing"},
            {"trend": "funniest sports and public fails", "listicle_theme": "funniest",
             "angle": "sports fails and harmless public mishaps"},
        ]
        requested_index = int(os.getenv("YOUTUBE_INDEX", "0") or "0")
        if requested_index in {1, 2, 3}:
            selected_topics = [(requested_index, listicle_formats[requested_index - 1])]
        else:
            selected_topics = list(enumerate(listicle_formats, 1))

        for youtube_index, item in selected_topics:
            topic = str(item.get("trend", "")).strip()
            youtube_opportunity = {
                "trend": topic,
                "listicle_theme": item.get("listicle_theme", "funniest"),
                "angle": item.get("angle", ""),
                "source": item.get("source", "listicle_format"),
                "sources": item.get("sources", []),
                "summary": item.get("summary", ""),
                "source_url": item.get("source_url", ""),
                "hook": f"Top 10 {topic}.",
                "format": "youtube_top10",
                "platform": "youtube",
                "confidence": item.get("confidence", 0.7),
                "status": "ready",
                "trend_metrics": item.get("metrics", {}),
            }
            try:
                youtube_path, youtube_manifest = create_youtube_commentary_video(
                    youtube_opportunity, youtube_index
                )
                youtube_outputs.append({
                    "trend": topic,
                    "video": youtube_path,
                    "manifest": youtube_manifest,
                    "platform": "youtube",
                    "format": "top_10_listicle",
                    "generation_mode": "real_footage_commentary",
                })
            except Exception as error:
                youtube_outputs.append({
                    "trend": topic,
                    "video": "",
                    "manifest": "",
                    "platform": "youtube",
                    "format": "top_10_listicle",
                    "generation_mode": "failed",
                    "error": str(error),
                })

        expected_youtube = len(selected_topics)
        if len(youtube_outputs) != expected_youtube:
            raise RuntimeError(
                f"YouTube quality gate failed: expected {expected_youtube} listicle(s), "
                f"created {len(youtube_outputs)}"
            )

    result["youtube_videos"] = youtube_outputs

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "run_summary.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if run_mode in {"normal", "both"}:
        qc = quality_check(result["videos"])
    else:
        qc = {"passed": True, "results": [], "mode": "youtube_only"}

    with open(os.path.join(OUTPUT_DIR, "quality_report.json"), "w", encoding="utf-8") as f:
        json.dump(qc, f, ensure_ascii=False, indent=2)

    state = record_learning(result, qc)
    save_learning_summary(state, OUTPUT_DIR)

    if not qc["passed"]:
        failed = [item for item in qc["results"] if not item["passed"]]
        details = "; ".join(
            f"video={item.get('video')}: {','.join(item.get('errors', []))}"
            for item in failed
        )
        raise RuntimeError(f"Quality control blocked Discord: {details}")

    for item in result["videos"]:
        item["publishing"] = publish(item["video"], item.get("script", {}))

    record_run(result)

    source_counts = {}
    for item in result["opportunities"]:
        for source in item.get("sources", [item.get("source", "unknown")]):
            source_counts[source] = source_counts.get(source, 0) + 1

    notify(
        f"🚀 Viral Video Automation complete\n"
        f"Mode: {run_mode} | Trends scanned: {result['trend_count']} | "
        f"Normal videos: {len(result['videos'])} | YouTube videos: {len(youtube_outputs)}\n"
        f"Sources represented: {', '.join(sorted(source_counts)) or 'none'}\n"
        f"Publishing: OFF"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
