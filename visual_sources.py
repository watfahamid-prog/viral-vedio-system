import hashlib
import html
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote
import requests

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ViralVideoBot/9.0"
STOP = {
    "this","that","with","from","about","after","before","more","most","into","over",
    "under","what","when","where","which","while","would","could","there","their",
    "here","news","latest","update","source","sources","kallor","källor","least",
    "one","died","dead","thing","things","moment","moments","caught","camera",
    "scene","show","shows","shot","camera","video","vertical","original","realistic",
    "natural","cinematic","footage","image","images","maintain","continuity",
}
GENERIC_BAD = {
    "book","books","page","pages","library","tribune","newspaper","magazine","texture",
    "background","gradient","logo","icon","poster","cover","screenshot","template",
    "technology","device","computer","office","abstract",
}
ALIASES = {
    "ryssland":"russia","ryska":"russia","ukraina":"ukraine","ukrainas":"ukraine",
    "attacker":"attack","attackerna":"attack","attack":"attack","anfall":"attack",
    "krig":"war","kriget":"war","missil":"missile","missiler":"missile",
    "drönare":"drone","dronare":"drone","drönarattack":"drone attack",
    "explosion":"explosion","explosioner":"explosion","död":"death","doda":"death",
    "minst":"at least","fotboll":"football","match":"match","mål":"goal",
    "bil":"car","bilar":"cars","hund":"dog","hundar":"dogs","katt":"cat","katter":"cats",
    "brand":"fire","översvämning":"flood","översvämningar":"flood",
    "jordbävning":"earthquake","jordskalv":"earthquake","storm":"storm",
    "demonstration":"protest","demonstranter":"protesters","polisen":"police",
    "polis":"police","sjukhus":"hospital","flyg":"airplane","tåg":"train",
    "robot":"robot","artificiell":"artificial","intelligens":"intelligence",
}

def _clean(text):
    return html.unescape(re.sub(r"<[^>]+>", " ", str(text or ""))).replace("&nbsp;", " ")

def _tokens(text):
    raw = re.findall(r"[A-Za-zÅÄÖåäö0-9][A-Za-zÅÄÖåäö0-9'’\-]+", _clean(text).lower())
    out = []
    for word in raw:
        if len(word) < 4 or word in STOP:
            continue
        alias = ALIASES.get(word, word)
        for part in alias.split():
            if len(part) >= 4 and part not in STOP:
                out.append(part)
    return list(dict.fromkeys(out))

def _queries(opportunity, search_text=None):
    trend = str(opportunity.get("trend", "")).strip()
    category = str(opportunity.get("category", "")).lower()
    summary = str(opportunity.get("summary", "")).strip()
    base = search_text or trend
    variants = []
    if base:
        variants.append(" ".join(_tokens(base)[:6]))
    translated = [ALIASES.get(w, w) for w in re.findall(r"[A-Za-zÅÄÖåäö0-9][A-Za-zÅÄÖåäö0-9'’\-]+", trend.lower())]
    translated = [w for w in translated if len(w) >= 4 and w not in STOP]
    if translated:
        variants.append(" ".join(dict.fromkeys(translated))[:100])
    if summary:
        summary_terms = _tokens(summary)
        if summary_terms:
            variants.append(" ".join(summary_terms[:5]))
    if category == "sports":
        variants.append(" ".join(_tokens(trend)[:4]) + " sports")
    elif category == "politics":
        variants.append(" ".join(_tokens(trend)[:4]) + " government")
    return [q.strip() for q in dict.fromkeys(variants) if q.strip()]

def _relevance(text, terms):
    hay = _clean(text).lower()
    if not terms:
        return 0
    strong = sum(1 for t in terms if t in hay)
    bad = sum(1 for b in GENERIC_BAD if re.search(r"\b" + re.escape(b) + r"\b", hay))
    score = strong * 3
    if len(terms) >= 2 and strong >= 2:
        score += 4
    if bad:
        score -= min(5, bad)
    return score

def _download(url, path, min_bytes=12000):
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, stream=True)
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
        if Path(path).stat().st_size < min_bytes:
            Path(path).unlink(missing_ok=True)
            return False
        return True
    except Exception as e:
        print(f"Visual download skipped: {e}")
        Path(path).unlink(missing_ok=True)
        return False

def _valid_image(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return min(im.size) >= 420
    except Exception:
        Path(path).unlink(missing_ok=True)
        return False

def _valid_video(path):
    try:
        result = subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration:stream=width,height",
             "-of","json",str(path)],
            capture_output=True,text=True,timeout=15,check=True)
        data = __import__("json").loads(result.stdout)
        duration = float(data.get("format",{}).get("duration",0) or 0)
        return duration >= 2 and any(int(s.get("width",0)) >= 480 and int(s.get("height",0)) >= 360
                                     for s in data.get("streams",[]) if s.get("width"))
    except Exception:
        Path(path).unlink(missing_ok=True)
        return False

def _source_image(opportunity, work, seen):
    url = str(opportunity.get("image_url","")).strip()
    if not url:
        return []
    p = Path(work) / "source_article.jpg"
    if _download(url, p) and _valid_image(p):
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest not in seen:
            seen.add(digest)
            return [str(p)]
    return []

def _commons(queries, work, seen, max_items=4):
    assets = []
    for query in queries[:3]:
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php", params={
                "action":"query","generator":"search","gsrsearch":query,"gsrnamespace":6,
                "gsrlimit":12,"prop":"imageinfo","iiprop":"url|extmetadata",
                "iiurlwidth":1400,"format":"json","formatversion":2,
            }, headers={"User-Agent":USER_AGENT}, timeout=15)
            if not r.ok:
                continue
            pages = r.json().get("query",{}).get("pages",[]) or []
            terms = _tokens(query)
            ranked=[]
            for page in pages:
                info=(page.get("imageinfo") or [{}])[0]
                meta=info.get("extmetadata") or {}
                hay=" ".join([
                    str(page.get("title","")),
                    str(meta.get("ObjectName",{}).get("value","")),
                    str(meta.get("ImageDescription",{}).get("value","")),
                    str(meta.get("Categories",{}).get("value","")),
                ])
                score=_relevance(hay,terms)
                if score < 6:
                    continue
                url=info.get("thumburl") or info.get("url")
                if url:
                    ranked.append((score,str(page.get("title","")),url))
            ranked.sort(key=lambda x:-x[0])
            for score,title,url in ranked:
                if len(assets)>=max_items:
                    break
                p=Path(work)/f"commons_{len(assets):02d}.jpg"
                if _download(url,p) and _valid_image(p):
                    digest=hashlib.sha256(p.read_bytes()).hexdigest()
                    if digest in seen:
                        p.unlink(missing_ok=True)
                        continue
                    seen.add(digest); assets.append(str(p))
        except Exception as e:
            print(f"Wikimedia search skipped: {e}")
    return assets

def _pexels(queries, work, seen, max_images=4, max_videos=3):
    images=[]; videos=[]; credits=[]
    key=os.getenv("PEXELS_API_KEY","").strip()
    if not key:
        return images,videos,credits
    headers={"Authorization":key,"User-Agent":USER_AGENT}
    for query in queries[:2]:
        try:
            r=requests.get("https://api.pexels.com/v1/search",headers=headers,
                           params={"query":query,"per_page":12,"orientation":"portrait"},timeout=20)
            if r.ok:
                terms=_tokens(query)
                for item in r.json().get("photos",[]):
                    hay=" ".join([str(item.get("alt","")),str(item.get("url",""))])
                    if _relevance(hay,terms) < 3:
                        continue
                    url=(item.get("src") or {}).get("large2x") or (item.get("src") or {}).get("large")
                    if not url: continue
                    p=Path(work)/f"pexels_photo_{len(images):02d}.jpg"
                    if _download(url,p) and _valid_image(p):
                        digest=hashlib.sha256(p.read_bytes()).hexdigest()
                        if digest not in seen:
                            seen.add(digest); images.append(str(p))
                            credits.append(f"Pexels photo: {item.get('url','')}")
                    if len(images)>=max_images: break
            rv=requests.get("https://api.pexels.com/v1/videos/search",headers=headers,
                            params={"query":query,"per_page":10,"orientation":"portrait","size":"medium"},timeout=25)
            if rv.ok:
                terms=_tokens(query)
                for item in rv.json().get("videos",[]):
                    hay=str(item.get("url",""))+" "+str(item.get("user",{}).get("name",""))
                    # Pexels' search is semantic; require a non-trivial query and avoid
                    # accepting a random generic result when the query is highly specific.
                    if len(terms)>=2 and not terms:
                        continue
                    files=item.get("video_files",[]) or []
                    files=sorted(files,key=lambda x:(x.get("width",0)<720, abs((x.get("height",1)/(x.get("width",1) or 1))-16/9)))
                    link=next((f.get("link") for f in files if str(f.get("file_type","")).startswith("video/mp4")),None)
                    if not link: continue
                    p=Path(work)/f"pexels_video_{len(videos):02d}.mp4"
                    if _download(link,p,min_bytes=50000) and _valid_video(p):
                        digest=hashlib.sha256(p.read_bytes()).hexdigest()
                        if digest not in seen:
                            seen.add(digest); videos.append(str(p))
                            credits.append(f"Pexels video: {item.get('url','')}")
                    if len(videos)>=max_videos: break
        except Exception as e:
            print(f"Pexels search skipped: {e}")
        if len(images)>=max_images and len(videos)>=max_videos:
            break
    return images[:max_images],videos[:max_videos],credits

def _pixabay(queries, work, seen, max_items=3):
    images=[]; credits=[]
    key=os.getenv("PIXABAY_API_KEY","").strip()
    if not key: return images,credits
    for query in queries[:2]:
        try:
            r=requests.get("https://pixabay.com/api/",params={
                "key":key,"q":query,"lang":"en","image_type":"photo","orientation":"vertical",
                "per_page":12,"safesearch":"true"
            },headers={"User-Agent":USER_AGENT},timeout=20)
            if not r.ok: continue
            terms=_tokens(query)
            for item in r.json().get("hits",[]):
                hay=str(item.get("tags",""))+" "+str(item.get("pageURL",""))
                if _relevance(hay,terms) < 3: continue
                url=item.get("largeImageURL") or item.get("webformatURL")
                if not url: continue
                p=Path(work)/f"pixabay_{len(images):02d}.jpg"
                if _download(url,p) and _valid_image(p):
                    digest=hashlib.sha256(p.read_bytes()).hexdigest()
                    if digest not in seen:
                        seen.add(digest); images.append(str(p))
                        credits.append(f"Pixabay: {item.get('pageURL','')}")
                if len(images)>=max_items: break
        except Exception as e:
            print(f"Pixabay search skipped: {e}")
        if len(images)>=max_items: break
    return images[:max_items],credits

def fetch_visual_media(opportunity, work, search_text=None, allow_source=True, max_images=6, max_videos=3):
    work=Path(work); work.mkdir(parents=True,exist_ok=True)
    seen=set(); images=[]; videos=[]; credits=[]
    if allow_source:
        images.extend(_source_image(opportunity,work,seen))
        if images:
            credits.append("Source article image")
    queries=_queries(opportunity,search_text)
    print("Visual search queries:", queries)
    pex_i,pex_v,pex_c=_pexels(queries,work,seen,max_images=max_images,max_videos=max_videos)
    images.extend(pex_i); videos.extend(pex_v); credits.extend(pex_c)
    if len(images)<max_images:
        images.extend(_commons(queries,work,seen,max_items=max_images-len(images)))
    if len(images)<max_images:
        pix_i,pix_c=_pixabay(queries,work,seen,max_items=max_images-len(images))
        images.extend(pix_i); credits.extend(pix_c)
    return images[:max_images],videos[:max_videos],credits[:max_images+max_videos+2]
