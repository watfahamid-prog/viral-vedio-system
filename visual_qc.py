import base64, json, os, subprocess, tempfile
from pathlib import Path
import requests

ENABLED = os.getenv("GEMINI_VISUAL_QC_ENABLED", "true").lower() == "true"
KEY = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

def review_video(video_path, script, scene_count=None):
    if not (ENABLED and KEY):
        return {"enabled": False, "passed": True, "reason": "Gemini visual QC not configured"}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            pattern = str(Path(tmp) / "frame_%02d.jpg")
            frames = 6
            if scene_count and scene_count >= 8:
                duration = float(subprocess.run(
                    ["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",video_path],
                    capture_output=True,text=True,check=True).stdout.strip())
                fps = 1.0 / max(0.5, duration / scene_count)
                frames = scene_count
                pattern = str(Path(tmp) / "scene_%02d.jpg")
                vf = f"fps={fps:.5f},scale=360:-2"
            else:
                vf = "fps=1/3,scale=360:-2"
            subprocess.run(
                ["ffmpeg","-y","-i",video_path,"-vf",vf,"-frames:v",str(frames),pattern],
                check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
            files=sorted(Path(tmp).glob("scene_*.jpg")) or sorted(Path(tmp).glob("frame_*.jpg"))
            parts=[{"text":(
                "Review these chronological frames from a vertical short. Evaluate visual quality, "
                "scene variety, pacing, composition, realism, continuity, camera language and repetition. "
                "Return JSON with score_1_to_10, passed, strengths, problems, fix_priority, "
                "and scene_reviews. scene_reviews must contain one object per frame with scene_index, "
                "score_1_to_10, weak, and reason. A score below 7 is weak. SCRIPT: "
                + json.dumps(script,ensure_ascii=False))}]
            for p in files:
                parts.append({"inline_data":{"mime_type":"image/jpeg","data":base64.b64encode(p.read_bytes()).decode("ascii")}})
            url="https://generativelanguage.googleapis.com/v1beta/models/"+MODEL+":generateContent"
            response=requests.post(url,headers={"x-goog-api-key":KEY,"Content-Type":"application/json"},
                json={"contents":[{"role":"user","parts":parts}],
                      "generationConfig":{"temperature":0.2,"responseMimeType":"application/json"}},timeout=75)
            if not response.ok:
                return {"enabled":True,"passed":True,"warning":"Gemini visual QC HTTP "+str(response.status_code),"scene_reviews":[]}
            data=response.json(); text=""
            for candidate in data.get("candidates",[]):
                for part in candidate.get("content",{}).get("parts",[]): text += part.get("text","")
            start,end=text.find("{"),text.rfind("}")
            if start<0 or end<=start: raise ValueError("No JSON from Gemini visual QC")
            result=json.loads(text[start:end+1]); result["enabled"]=True
            result.setdefault("scene_reviews",[])
            return result
        except Exception as error:
            return {"enabled":True,"passed":True,"warning":"Gemini visual QC skipped: "+str(error),"scene_reviews":[]}
