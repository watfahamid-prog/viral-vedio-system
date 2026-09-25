import os
import video_v2 as _v

_original_run = _v.subprocess.run

def _stable_run(cmd, *args, **kwargs):
    if isinstance(cmd, list) and "-f" in cmd and "concat" in cmd and "-i" in cmd:
        fixed = list(cmd)
        try:
            inp = fixed[fixed.index("-i") + 1]
            if str(inp).endswith(".txt") and os.path.exists(inp):
                lines = []
                for line in open(inp, encoding="utf-8"):
                    if line.startswith("file '") and line.rstrip().endswith("'"):
                        raw = line.rstrip()[6:-1]
                        if not os.path.isabs(raw):
                            raw = os.path.abspath(raw)
                        lines.append("file '" + raw + "'\n")
                    else:
                        lines.append(line)
                open(inp, "w", encoding="utf-8").writelines(lines)
        except Exception:
            pass
        if "-c" in fixed:
            ci = fixed.index("-c")
            if ci + 1 < len(fixed) and fixed[ci + 1] == "copy":
                fixed[ci:ci + 2] = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-r", str(_v.FPS)]
                cmd = fixed
    return _original_run(cmd, *args, **kwargs)

_v.subprocess.run = _stable_run
create_video = _v.create_video
write_manifest = _v.write_manifest
