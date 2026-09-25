import os
import math
import json
from pathlib import Path

# Runtime upgrade layer: keeps the core modules stable while adding the new
# shot, platform, quality-control and learning behavior.
try:
    import video

    video.AI_VIDEO_MAX_CLIPS = 11

    def _shot_count(duration):
        return max(4, min(11, int(math.ceil(float(duration) / 4.0))))

    def _visual_prompt(opportunity, scene):
        platform = str(opportunity.get("platform", "youtube")).lower()
        trend = str(opportunity.get("trend", "current topic"))
        category = str(opportunity.get("category", "general"))
        if platform == "tiktok":
            direction = "TikTok-first, creator-like, immediate hook, rapid visual changes, sound-on energy, keep important visuals away from UI edges."
        else:
            direction = "YouTube Shorts-first, strong opening visual, clear story progression, clean central framing and satisfying payoff."
        return (
            "Create an ORIGINAL high-energy 9:16 short-form video shot. "
            "Real moving footage, never a slideshow, poster, presentation or text card. "
            "Show a clear subject performing a visible action with continuous movement. "
            "Use colorful environments, dynamic camera motion, depth, expressive action, strong lighting and visual surprise. "
            "No readable text, subtitles, captions, logos or watermarks. "
            f"{direction} Topic: {trend}. Category: {category}. "
            f"Shot idea: {scene}. Make it understandable with sound muted and visually consistent with the other shots."
        )

    def _make_ai_visuals(opportunity, script_data, duration, run_id):
        if not video.engine_available():
            return None
        requested = script_data.get("visual_scenes") or script_data.get("scenes") or []
        count = _shot_count(duration)
        shots = [str(x).strip() for x in requested if str(x).strip()]
        if not shots:
            shots = [str(script_data.get("hook", opportunity.get("trend", "current topic")))]
        while len(shots) < count:
            shots.append(f"New action beat and camera angle connected to {opportunity.get('trend', 'the topic')}")
        shots = shots[:count]

        clip_dir = os.path.join(video.OUTPUT_DIR, f"ai-clips-{run_id}")
        os.makedirs(clip_dir, exist_ok=True)
        clips = []
        for i, scene in enumerate(shots):
            path = os.path.join(clip_dir, f"clip_{i:02d}.mp4")
            try:
                if video.generate_clip(_visual_prompt(opportunity, scene), path, duration=max(3, duration / count)):
                    clips.append(path)
            except Exception as error:
                print(f"AI shot {i + 1}/{count} failed: {error}")

        if not clips:
            import shutil
            shutil.rmtree(clip_dir, ignore_errors=True)
            return None

        concat_list = os.path.join(clip_dir, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for clip in clips:
                f.write(f"file '{os.path.abspath(clip)}'\n")

        visual = os.path.join(video.OUTPUT_DIR, f"ai_visuals_{run_id}.mp4")
        try:
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                 "-vf", f"scale={video.WIDTH}:{video.HEIGHT}:force_original_aspect_ratio=increase,crop={video.WIDTH}:{video.HEIGHT},setsar=1",
                 "-t", str(duration), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", visual],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return visual
        except Exception as error:
            print(f"AI shot assembly failed: {error}")
            return None
        finally:
            import shutil
            shutil.rmtree(clip_dir, ignore_errors=True)

    video._shot_count = _shot_count
    video._visual_prompt = _visual_prompt
    video._make_ai_visuals = _make_ai_visuals
except Exception as error:
    print(f"Runtime video upgrade unavailable: {error}")


# Platform policy: guarantee that a run produces dedicated YouTube Shorts and
# TikTok concepts instead of generic cross-posts.
try:
    import pipeline
    original_run_pipeline = pipeline.run_pipeline

    def run_pipeline_with_platforms():
        result = original_run_pipeline()
        opportunities = result.get("opportunities", [])
        for i, item in enumerate(opportunities):
            if i % 2 == 0:
                item["platform"] = "youtube"
                item["format"] = "youtube_ranked_breakdown" if i % 4 == 0 else "youtube_quick_explainer"
            else:
                item["platform"] = "tiktok"
                item["format"] = "tiktok_cantina_story"
            item["platform_strategy"] = "youtube_shorts_native" if item["platform"] == "youtube" else "tiktok_native"
        return result

    pipeline.run_pipeline = run_pipeline_with_platforms
except Exception as error:
    print(f"Platform policy unavailable: {error}")


# Quality control happens inside the notification boundary, so Discord is never
# told a run is complete before the final MP4 files have passed validation.
try:
    import discord
    from quality_control import quality_check
    from learning import record_learning, save_learning_summary

    original_notify = discord.notify

    def notify_after_qc(message):
        result = {"videos": []}
        try:
            if os.path.exists(os.path.join("output", "run_summary.json")):
                with open(os.path.join("output", "run_summary.json"), "r", encoding="utf-8") as f:
                    result = json.load(f)
        except Exception:
            pass

        qc = quality_check(result.get("videos", []))
        os.makedirs("output", exist_ok=True)
        with open(os.path.join("output", "quality_report.json"), "w", encoding="utf-8") as f:
            json.dump(qc, f, ensure_ascii=False, indent=2)

        state = record_learning(result, qc)
        save_learning_summary(state, "output")

        if not qc["passed"]:
            failed = [x for x in qc["results"] if not x["passed"]]
            details = "; ".join(f"{x.get('trend')}: {','.join(x.get('errors', []))}" for x in failed)
            print(f"QUALITY CONTROL BLOCKED DISCORD: {details}")
            return False

        return original_notify(
            message + f"\nQC: PASS ({qc['passed_count']}/{qc['total_count']})"
            + f"\nLearning state: {state.get('runs', 0)} runs recorded"
        )

    discord.notify = notify_after_qc
except Exception as error:
    print(f"Quality-control runtime upgrade unavailable: {error}")
