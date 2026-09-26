import json, math, os, subprocess
from pathlib import Path
import video_v4 as v4

WIDTH, HEIGHT, FPS = v4.WIDTH, v4.HEIGHT, v4.FPS
OUTPUT_DIR = v4.OUTPUT_DIR


def _scene_prompts(script, count):
    visual = [str(x).strip() for x in (script.get("visual_scenes") or []) if str(x).strip()]
    scenes = [str(x).strip() for x in (script.get("scenes") or []) if str(x).strip()]
    plan = script.get("shot_plan") or []
    bible = script.get("continuity_bible") or {}
    out = []
    camera_variants = [
        "wide establishing shot with a slow push-in",
        "tight close-up with handheld micro-movement",
        "medium tracking shot moving laterally",
        "low-angle reveal with foreground depth",
        "over-shoulder shot with a gentle rack-focus feel",
        "high-angle top-down detail shot",
        "macro insert with controlled camera drift",
        "dynamic follow shot with clear subject motion",
        "static composed wide shot followed by subject movement",
        "three-quarter profile with a slow orbit",
    ]
    for i in range(count):
        base = visual[i] if i < len(visual) else (visual[i % len(visual)] if visual else (scenes[i % len(scenes)] if scenes else "Dynamic documentary scene"))
        if i < len(plan) and isinstance(plan[i], dict):
            item = plan[i]
            base = str(item.get("visual_prompt") or base).strip()
            details = " ".join([
                str(item.get("shot_type", "")),
                str(item.get("camera", "")),
                str(item.get("action", "")),
            ]).strip()
            if details:
                base += " " + details
        continuity = " ".join(str(v) for v in bible.values() if v)
        if continuity:
            base += " Maintain continuity: " + continuity
        base += " Camera variation: " + camera_variants[i % len(camera_variants)] + "."
        base += " Original footage, realistic physics, no readable text, no logos, no watermark."
        out.append(base)
    return out


def _build_segment_v5(keyframe, output, seconds, direction, first=False, last=False):
    frames = max(1, int(round(seconds * FPS)))
    zoom_step = 0.0026 if direction > 0 else 0.0021
    zoom = f"min(zoom+{zoom_step:.5f},1.20)"
    if direction > 0:
        x = "iw/2-(iw/zoom/2)+((iw-iw/zoom)*0.34)"
        y = "ih/2-(ih/zoom/2)+((ih-ih/zoom)*0.20)"
    else:
        x = "iw/2-(iw/zoom/2)-((iw-iw/zoom)*0.30)"
        y = "ih/2-(ih/zoom/2)-((ih-ih/zoom)*0.16)"
    filters = [
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}",
        "format=yuv420p",
    ]
    if first:
        filters.append("fade=t=in:st=0:d=0.16")
    if last:
        filters.append(f"fade=t=out:st={max(0, seconds-0.16):.3f}:d=0.16")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", keyframe,
            "-vf", ",".join(filters), "-t", f"{seconds:.3f}",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", output,
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _concat_with_transitions(segments, output, transition=0.12):
    if len(segments) == 1:
        Path(output).write_bytes(Path(segments[0]).read_bytes())
        return
    inputs = []
    for segment in segments:
        inputs += ["-i", segment]

    durations = []
    for segment in segments:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", segment,
            ],
            capture_output=True, text=True, check=True,
        )
        durations.append(float(result.stdout.strip()))

    graph = []
    current = "0:v"
    elapsed = 0.0
    for i in range(1, len(segments)):
        elapsed += durations[i - 1] - transition
        out = f"v{i}"
        graph.append(
            f"[{current}][{i}:v]xfade=transition=fade:duration={transition}:offset={elapsed:.3f}[{out}]"
        )
        current = out

    subprocess.run(
        [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", ";".join(graph),
            "-map", f"[{current}]",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", output,
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )


def _make_polished_audio(script, work, duration):
    voice = v4._make_audio(script, work, duration)
    try:
        from audio_enhancements import elevenlabs_tts
        eleven_path = Path(work) / "eleven_voice.mp3"
        upgraded = elevenlabs_tts(v4._speech(script), str(eleven_path))
        if upgraded:
            converted = Path(work) / "voice_eleven.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-i", upgraded, "-ar", "48000", "-ac", "1",
                 "-c:a", "pcm_s16le", str(converted)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            voice = str(converted)
            print("Voice engine: ElevenLabs free tier")
    except Exception as error:
        print(f"Optional ElevenLabs voice skipped: {error}")
    if not voice:
        return None

    bed = Path(work) / "ambient.wav"
    mixed = Path(work) / "polished_audio.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"anoisesrc=color=brown:amplitude=0.018:duration={duration}",
            "-filter:a",
            f"lowpass=f=900,volume=0.16,afade=t=in:st=0:d=1.0,"
            f"afade=t=out:st={max(0, duration-1.0):.3f}:d=1.0",
            "-ar", "48000", "-ac", "1", str(bed),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", voice, "-i", str(bed),
            "-filter_complex",
            "[0:a]loudnorm=I=-15:TP=-1.5:LRA=7,aresample=48000[v];"
            "[1:a]aresample=48000[b];"
            "[v][b]amix=inputs=2:duration=first:dropout_transition=0,"
            "alimiter=limit=0.95[a]",
            "-map", "[a]", "-t", str(duration),
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(mixed),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return str(mixed)


def create_video(opportunity, script, index=1):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    slug = v4._slug(opportunity.get("trend", "trend"))
    run_id = f"{index:02d}-{slug}"
    work = Path(OUTPUT_DIR) / f"v5-{run_id}"
    work.mkdir(parents=True, exist_ok=True)

    duration = v4.duration_for(script, opportunity)
    scenes = [str(x).strip() for x in (script.get("scenes") or []) if str(x).strip()]
    if not scenes:
        scenes = [str(script.get("hook") or opportunity.get("trend", "Current topic"))]

    target = max(8, min(10, math.ceil(duration / 2.35)))
    while len(scenes) < target:
        scenes.append(scenes[-1])
    scenes = scenes[:target]

    visuals = _scene_prompts(script, target)
    title = str(script.get("title") or opportunity.get("trend", "Current topic"))
    hook = str(script.get("hook") or opportunity.get("hook", "Here is what is happening."))
    category = str(opportunity.get("category", "general"))
    palette = v4.PALETTES[(index - 1) % len(v4.PALETTES)]
    style = (index - 1) % 6
    transition = min(0.14, max(0.08, (duration / target) * 0.07))
    scene_time = (duration + transition * (target - 1)) / target

    assets, credits = v4._fetch_visual_assets(opportunity, work)
    keys = []
    for i, scene in enumerate(scenes):
        key = work / f"key_{i:02d}.jpg"
        if assets:
            asset = assets[i % len(assets)]
            v4._photo_frame(
                str(key), asset, title, hook, visuals[i], category,
                i, target, palette, (style + i) % 6,
            )
        else:
            v4._render_frame(
                str(key), title, hook, visuals[i], category,
                i, target, palette, (style + i) % 6,
            )
        keys.append(str(key))

    segments = []
    for i, key in enumerate(keys):
        segment = work / f"seg_{i:02d}.mp4"
        _build_segment_v5(
            key, str(segment), scene_time,
            direction=1 if (i + style) % 2 == 0 else -1,
            first=i == 0, last=i == len(keys) - 1,
        )
        segments.append(str(segment))

    # If a real AI-video provider is configured, replace up to three spaced scenes
    # with generated motion. The local renderer remains the reliable fallback.
    try:
        from ai_video import generate_clip, engine_available
        if engine_available():
            max_ai = min(6, max(0, int(os.getenv("AI_VIDEO_MAX_CLIPS", "6"))))
            # Spread AI motion across the timeline so the short opens, escalates and finishes with real motion.
            # AI-first: distribute generated motion across the whole story.
            max_ai = min(max_ai, target)
            if max_ai >= target:
                candidate_indexes = list(range(target))
            else:
                candidate_indexes = []
                for n in range(max_ai):
                    idx = round(n * (target - 1) / max(1, max_ai - 1))
                    if idx not in candidate_indexes:
                        candidate_indexes.append(idx)
            used = []
            for ai_i in candidate_indexes:
                if len(used) >= max_ai or ai_i >= target or ai_i in used:
                    continue
                prompt = (
                    f"Vertical 9:16 original cinematic footage. {visuals[ai_i]} "
                    "Natural physical motion, coherent subject, realistic lighting, documentary quality, "
                    "no readable text, no logos, no watermark, no celebrity likeness."
                )
                ai_path = work / f"ai_scene_{ai_i:02d}.mp4"
                generated = generate_clip(
                    prompt, str(ai_path),
                    duration=min(5, max(3, int(round(scene_time)))),
                    image_path=key,
                )
                if generated and Path(generated).exists():
                    normalized = work / f"ai_scene_{ai_i:02d}_norm.mp4"
                    subprocess.run(
                        [
                            "ffmpeg", "-y", "-i", generated,
                            "-vf",
                            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                            f"crop={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p",
                            "-an", "-t", f"{scene_time:.3f}",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                            "-movflags", "+faststart", str(normalized),
                        ],
                        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    segments[ai_i] = str(normalized)
                    used.append(ai_i)
            print(f"AI motion scenes used: {len(used)}")
    except Exception as error:
        print(f"AI motion scene enhancement skipped: {error}")

    silent = work / "silent.mp4"
    _concat_with_transitions(segments, str(silent), transition=transition)

    # Creative feedback loop: inspect the assembled draft, then replace only weak scenes.
    # This avoids spending AI-generation credits on every scene.
    regeneration_count = 0
    visual_review = {}
    try:
        from visual_qc import review_video
        visual_review = review_video(str(silent), script, scene_count=target)
        weak = []
        for item in visual_review.get("scene_reviews", []):
            try:
                if bool(item.get("weak")) or float(item.get("score_1_to_10", 10)) < 7:
                    weak.append(int(item.get("scene_index", -1)))
            except Exception:
                continue
        weak = [i for i in dict.fromkeys(weak) if 0 <= i < target][:2]
        if weak:
            from ai_video import generate_clip, engine_available
            from creative_director import repair_weak_shot
            if engine_available():
                for weak_i in weak:
                    review_item = next((x for x in visual_review.get("scene_reviews", [])
                                        if int(x.get("scene_index", -1)) == weak_i), {})
                    reason = review_item.get("reason", "weak visual quality or repetition")
                    repaired_prompt = repair_weak_shot(script, weak_i, reason)
                    prompt = repaired_prompt or (
                        "REGENERATE THIS WEAK SHOT. Make it visually premium, physically plausible, "
                        "dynamic and clearly different from neighboring shots. Use a distinct camera "
                        "movement, composition, action and environment depth. Avoid static slideshow/card "
                        "visuals, blue gradients, repeated backgrounds, readable text, logos and watermarks. "
                        "Vertical 9:16. " + visuals[weak_i]
                    )
                    retry_path = work / f"regen_scene_{weak_i:02d}.mp4"
                    generated = generate_clip(
                        prompt, str(retry_path),
                        duration=min(5, max(3, int(round(scene_time)))),
                        image_path=keys[weak_i],
                    )
                    if generated and Path(generated).exists():
                        normalized = work / f"regen_scene_{weak_i:02d}_norm.mp4"
                        subprocess.run(
                            ["ffmpeg","-y","-i",generated,
                             "-vf",f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                                   f"crop={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p",
                             "-an","-t",f"{scene_time:.3f}","-c:v","libx264",
                             "-preset","veryfast","-crf","18","-movflags","+faststart",
                             str(normalized)],
                            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                        segments[weak_i] = str(normalized)
                        regeneration_count += 1
                if regeneration_count:
                    _concat_with_transitions(segments, str(silent), transition=transition)
    except Exception as error:
        print(f"Creative regeneration loop skipped: {error}")

    audio = _make_polished_audio(script, work, duration)
    if not audio:
        raise RuntimeError("Narration engine unavailable; refusing to create a silent video.")
    # Free local sound-design layer: three subtle transition whooshes.
    try:
        sfx = work / "transition_sfx.wav"
        generated_sfx = None
        try:
            from audio_enhancements import elevenlabs_sfx
            generated_sfx = elevenlabs_sfx(
                "short cinematic whoosh transition, subtle, clean, modern social video",
                str(work / "eleven_transition.mp3"), duration=0.8
            )
        except Exception:
            generated_sfx = None
        if generated_sfx:
            subprocess.run(
                ["ffmpeg","-y","-i",generated_sfx,"-ar","48000","-ac","1",
                 "-filter:a","afade=t=in:st=0:d=0.05,afade=t=out:st=0.65:d=0.12,volume=0.10",
                 str(sfx)],
                check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i",
                 "sine=frequency=640:duration=0.22",
                 "-af", "afade=t=in:st=0:d=0.03,afade=t=out:st=0.16:d=0.06,lowpass=f=2400,volume=0.045",
                 "-ar", "48000", "-ac", "1", str(sfx)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        enhanced = work / "audio_sfx.wav"
        delay1 = max(500, int(duration * 250))
        delay2 = max(900, int(duration * 500))
        delay3 = max(1200, int(duration * 750))
        graph = (
            "[1:a]adelay=" + str(delay1) + "|" + str(delay1) + "[s1];"
            "[1:a]adelay=" + str(delay2) + "|" + str(delay2) + "[s2];"
            "[1:a]adelay=" + str(delay3) + "|" + str(delay3) + "[s3];"
            "[0:a][s1][s2][s3]amix=inputs=4:duration=first,alimiter=limit=0.95[out]"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio, "-i", str(sfx), "-filter_complex", graph,
             "-map", "[out]", "-t", str(duration), "-ar", "48000", "-ac", "1",
             "-c:a", "pcm_s16le", str(enhanced)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        audio = str(enhanced)
    except Exception as error:
        print(f"Local transition SFX skipped: {error}")

    captions = v4._make_captions(script, duration, work)
    final_tmp = work / "final.mp4"
    subtitle_filter = captions.replace("\\", "/").replace(":", "\\:")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(silent), "-i", audio,
            "-vf", f"ass='{subtitle_filter}'",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-t", str(duration), "-movflags", "+faststart", str(final_tmp),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    out = Path(OUTPUT_DIR) / f"viral_short_v5_{run_id}.mp4"
    os.replace(final_tmp, out)
    manifest = {
        "trend": opportunity.get("trend"),
        "visual_assets": assets,
        "visual_asset_credits": credits,
        "format": opportunity.get("format", "short_explainer"),
        "platform": opportunity.get("platform", "shorts"),
        "duration_seconds": duration,
        "scene_count": target,
        "audio": True,
        "captions": True,
        "original_content": True,
        "visual_engine": "viral_v7_hybrid_ai_motion_editorial_engine",
        "ai_motion_scenes": len(used) if "used" in locals() else 0,
        "ai_engines_available": __import__("ai_video").available_engines() if __import__("ai_video").engine_available() else [],
        "scene_changes": target - 1,
        "transition": "crossfade",
        "camera_motion": "alternating_push_pull",
        "visual_directions_used": len(visuals),
        "creative_qc_enabled": bool(visual_review.get("enabled")),
        "creative_qc_score": visual_review.get("score_1_to_10"),
        "weak_scenes_regenerated": regeneration_count,
        "final_visual_qc": visual_review,
        "continuity_bible": script.get("continuity_bible", {}),
        "shot_plan": script.get("shot_plan", []),
        "art_direction": f"palette-{(index-1)%len(v4.PALETTES)+1}/dynamic-layouts",
        "script": script,
        "video_file": str(out),
    }
    out.with_suffix(".json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(out)
