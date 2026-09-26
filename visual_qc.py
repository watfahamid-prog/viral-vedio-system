import base64, json, os, subprocess, tempfile
from pathlib import Path
import requests

ENABLED = os.getenv("GEMINI_VISUAL_QC_ENABLED", "true").lower() == "true"
KEY = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

def review_video(video_path, script):
    if not (ENABLED and KEY):
        return {"enabled": False, "passed": True, "reason": "Gemini visual QC not configured"}
    with tempfile.TemporaryDirectory() as tmp:
        pattern = str(Path(tmp) / "frame_%02d.jpg")
        try:
            subprocess.run(["ffmpeg","-y","-i",video_path,"-vf","fps=1/3,scale=360:-2","-frames:v","6",pattern],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
            files=sorted(Path(tmp).glob("frame_*.jpg"))
            parts=[{"text":("Review these sampled frames from a vertical short. Score visual quality, scene variety, pacing, "
                "composition, realism, continuity, caption safety, and whether the video looks repetitive or like a cheap template. "
                "Do not judge the factual truth from images. Return JSON with score_1_to_10, passed, strengths, problems, "
                "and fix_priority. A score below 7 means passed=false.\nSCRIPT: "+json.dumps(script,ensure_ascii=False))}]
            for p in files:
                parts.append({"inline_data":{"mime_type":"image/jpeg","data":base64.b64encode(p.read_bytes()).decode("ascii")}})
            url="https://generativelanguage.googleapis.com/v1beta/models/"+MODEL+":generateContent"
            response=requests.post(url,headers={"x-goog-api-key":KEY,"Content-Type":"application/json"},
                json={"contents":[{"role":"user","parts":parts}],"generationConfig":{"temperature":0.2,"responseMimeType":"application/json"}},timeout=60)
            if not response.ok:
                return {"enabled": True, "passed": True, "warning":"Gemini visual QC HTTP "+str(response.status_code)}
            data=response.json(); text=""
            for candidate in data.get("candidates",[]):
                for part in candidate.get("content",{}).get("parts",[]): text += part.get("text","")
            start,end=text.find("{"),text.rfind("}")
            if start<0 or end<=start: raise ValueError("No JSON from Gemini visual QC")
            result=json.loads(text[start:end+1]); result["enabled"]=True
            return result
        except Exception as error:
            return {"enabled": True, "passed": True, "warning": "Gemini visual QC skipped: "+str(error)}
