import json
import os
from pipeline import run_pipeline
from video_v4 import create_video, write_manifest
from script_generator import generate_script
from publish import publish
from discord import notify
from config import OUTPUT_DIR, VIDEO_COUNT, VIDEO_ENGINE
from performance import record_run
from self_test import main as run_self_test
from quality_control import quality_check
from learning import record_learning, save_learning_summary, learning_context


def main():
    run_self_test()
    print('Learning context:', learning_context())
    result = run_pipeline()
    result["videos"] = []

    if not result["opportunities"]:
        raise RuntimeError("No trend opportunities were found. Nothing was generated.")

    for index, opportunity in enumerate(result["opportunities"][:VIDEO_COUNT], 1):
        script = generate_script(
            opportunity["trend"], opportunity["hook"],
            opportunity.get("format", "short_explainer"),
            opportunity.get("summary", ""),
            opportunity.get("source_url", ""),
        )
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
            "platform": opportunity.get("platform", "shorts"),
            "format": opportunity.get("format", "short_explainer"),
            "confidence": opportunity.get("confidence", 0),
            "script": script,
            "publishing": {"status": "pending_quality_control"},
        })

    expected = min(VIDEO_COUNT, len(result["opportunities"]))
    if len(result["videos"]) != expected:
        raise RuntimeError(f"Pipeline quality gate failed: expected {expected} videos, created {len(result['videos'])}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "run_summary.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    qc = quality_check(result['videos'])
    with open(os.path.join(OUTPUT_DIR, 'quality_report.json'), 'w', encoding='utf-8') as f:
        json.dump(qc, f, ensure_ascii=False, indent=2)
    state = record_learning(result, qc)
    save_learning_summary(state, OUTPUT_DIR)
    if not qc['passed']:
        failed = [item for item in qc['results'] if not item['passed']]
        details = '; '.join(f"video={item.get('video')}: {','.join(item.get('errors', []))}" for item in failed)
        raise RuntimeError(f'Quality control blocked Discord: {details}')
    for item in result['videos']:
        item['publishing'] = publish(item['video'], item.get('script', {}))

    record_run(result)

    source_counts = {}
    for item in result["opportunities"]:
        for source in item.get("sources", [item.get("source", "unknown")]):
            source_counts[source] = source_counts.get(source, 0) + 1

    notify(
        f"🚀 Viral Video Automation complete\n"
        f"Trends scanned: {result['trend_count']} | Videos: {len(result['videos'])}\n"
        f"Sources represented: {', '.join(sorted(source_counts)) or 'none'}\n"
        f"Video styles: kinetic motion v4 + optional AI hero\n"
        f"Publishing: OFF (YouTube API is intentionally the final integration)"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
