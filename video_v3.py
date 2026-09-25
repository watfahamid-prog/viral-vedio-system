import video_v2 as _v

_original_run = _v.subprocess.run

def _stable_run(cmd, *args, **kwargs):
    if isinstance(cmd, list) and "-f" in cmd and "concat" in cmd and "-c" in cmd and "copy" in cmd:
        fixed = list(cmd)
        ci = fixed.index("-c")
        if ci + 1 < len(fixed) and fixed[ci + 1] == "copy":
            fixed[ci:ci + 2] = [
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-pix_fmt", "yuv420p", "-r", str(_v.FPS)
            ]
            cmd = fixed
    return _original_run(cmd, *args, **kwargs)

_v.subprocess.run = _stable_run

create_video = _v.create_video
write_manifest = _v.write_manifest
