from __future__ import annotations
import io, math, uuid
from datetime import date
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
DATA = "https://planetarycomputer.microsoft.com/api/data/v1"
CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)

app = FastAPI(title="GeoSentinel AI", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True
)

class SearchBody(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(5, gt=0, le=50)
    start: date
    end: date
    cloud: float = Field(20, ge=0, le=100)

class AnalyzeBody(BaseModel):
    before_id: str
    after_id: str
    query: str
    lat: float
    lon: float
    radius_km: float

def bbox(lat, lon, km):
    dlat = km / 111.32
    dlon = km / (111.32 * max(0.1, math.cos(math.radians(lat))))
    return [lon-dlon, lat-dlat, lon+dlon, lat+dlat]

def get_json(url, **kwargs):
    r = requests.get(url, timeout=90, **kwargs)
    r.raise_for_status()
    return r.json()

def post_json(url, payload):
    r = requests.post(url, json=payload, timeout=90)
    r.raise_for_status()
    return r.json()

@app.get("/api/health")
def health():
    return {"ok": True, "data_source": "Microsoft Planetary Computer / Sentinel-2 L2A"}

@app.post("/api/search")
def search(b: SearchBody):
    payload = {
        "collections": ["sentinel-2-l2a"],
        "bbox": bbox(b.lat, b.lon, b.radius_km),
        "datetime": f"{b.start}T00:00:00Z/{b.end}T23:59:59Z",
        "limit": 24,
        "query": {"eo:cloud_cover": {"lt": b.cloud}},
        "sortby": [{"field": "datetime", "direction": "desc"}]
    }
    try:
        data = post_json(f"{STAC}/search", payload)
    except Exception as e:
        raise HTTPException(502, f"STAC search failed: {e}")

    out = []
    for x in data.get("features", []):
        p = x.get("properties", {})
        a = x.get("assets", {})
        preview = (a.get("rendered_preview") or a.get("thumbnail") or {}).get("href")
        out.append({
            "id": x["id"],
            "datetime": p.get("datetime"),
            "cloud": p.get("eo:cloud_cover"),
            "bbox": x.get("bbox"),
            "geometry": x.get("geometry"),
            "preview": preview,
            "assets": list(a.keys())
        })
    return {"scenes": out, "bbox": payload["bbox"], "query": payload}

def item(item_id):
    return get_json(f"{STAC}/collections/sentinel-2-l2a/items/{item_id}")

def sign(href):
    if "blob.core.windows.net" not in href:
        return href
    return get_json(SAS, params={"href": href})["href"]

def asset_bytes(it, key):
    a = it.get("assets", {}).get(key)
    if not a: return None
    href = sign(a["href"])
    r = requests.get(href, timeout=240)
    r.raise_for_status()
    return r.content

def band(content, size=(1024,1024)):
    import rasterio
    with rasterio.open(io.BytesIO(content)) as ds:
        x = ds.read(1).astype(np.float32)
    x = cv2.resize(x, size, interpolation=cv2.INTER_AREA)
    return x

def stretch(x):
    valid = x[x > 0]
    lo, hi = (np.percentile(valid,2), np.percentile(valid,98)) if valid.size else (0,1)
    return np.clip((x-lo)/max(hi-lo,1e-6),0,1)

def rgb(it):
    chans = []
    for k in ["B04","B03","B02"]:
        c = asset_bytes(it,k)
        if c is None: return None
        chans.append(stretch(band(c)))
    return (np.stack(chans,-1)*255).astype(np.uint8)

def ndvi(it):
    n, r = asset_bytes(it,"B08"), asset_bytes(it,"B04")
    if n is None or r is None: return None
    N, R = band(n), band(r)
    return (N-R)/(N+R+1e-6)

def align_and_change(a,b):
    ag = cv2.cvtColor(a,cv2.COLOR_RGB2GRAY)
    bg = cv2.cvtColor(b,cv2.COLOR_RGB2GRAY)
    warp = np.eye(2,3,dtype=np.float32)
    try:
        crit=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,120,1e-5)
        cv2.findTransformECC(ag,bg,warp,cv2.MOTION_AFFINE,crit)
        ag=cv2.warpAffine(ag,warp,(bg.shape[1],bg.shape[0]),flags=cv2.INTER_LINEAR+cv2.WARP_INVERSE_MAP)
    except cv2.error:
        pass
    diff=cv2.absdiff(ag,bg)
    med=float(np.median(diff))
    mad=float(np.median(np.abs(diff-med)))+1
    th=max(18,med+3.0*mad)
    mask=(diff>th).astype(np.uint8)*255
    k=np.ones((7,7),np.uint8)
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,k)
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,k)
    n, lab, stats, cents=cv2.connectedComponentsWithStats(mask)
    features=[]
    for i in range(1,n):
        x,y,w,h,area=map(int,stats[i])
        if area<180: continue
        conf=min(.99,.55+area/25000)
        features.append({"id":len(features)+1,"x":x,"y":y,"w":w,"h":h,"area_px":area,"confidence":round(conf,3)})
    return mask,features,float(th)

def semantic(query, change_features, ndvi_info):
    q=query.lower()
    concepts=[
        ("New construction",["building","construction","structure","infrastructure"]),
        ("Road expansion",["road","highway","transport"]),
        ("Vegetation change",["vegetation","forest","crop","agriculture","green"]),
        ("Water change",["water","lake","river","reservoir"]),
        ("Bare/exposed land",["soil","bare","land","excavation"]),
        ("Industrial infrastructure",["industrial","factory","facility"])
    ]
    # Transparent deterministic semantic prior from the user's query, combined with observed signals.
    scores=[]
    for label,words in concepts:
        hits=sum(1 for w in words if w in q)
        score=.22 + .12*hits
        if ndvi_info and label=="Vegetation change":
            score += min(.32, abs(ndvi_info["mean_delta"])*1.8)
        if label in ("New construction","Road expansion","Industrial infrastructure"):
            score += min(.28,len(change_features)/35)
        scores.append({"label":label,"score":round(min(.96,score),3)})
    return sorted(scores,key=lambda x:x["score"],reverse=True)

def save_rgb(name, arr):
    path=CACHE/name
    import PIL.Image
    PIL.Image.fromarray(arr).save(path,quality=88)
    return path.name

@app.post("/api/analyze")
def analyze(b: AnalyzeBody):
    before=item(b.before_id); after=item(b.after_id)
    A=rgb(before); B=rgb(after)
    if A is None or B is None:
        raise HTTPException(422,"RGB assets unavailable for selected scenes")
    mask, feats, threshold=align_and_change(A,B)

    bn,an=ndvi(before),ndvi(after)
    ndvi_info=None
    if bn is not None and an is not None:
        delta=an-bn
        ndvi_info={
            "mean_delta":round(float(np.mean(delta)),4),
            "loss_fraction":round(float(np.mean(delta < -.15)),4),
            "gain_fraction":round(float(np.mean(delta > .15)),4)
        }

    before_file=save_rgb(f"{uuid.uuid4()}_before.jpg",A)
    after_file=save_rgb(f"{uuid.uuid4()}_after.jpg",B)
    mask_file=save_rgb(f"{uuid.uuid4()}_mask.png",mask)

    # Approximate map coordinates for visualization inside AOI.
    for f in feats:
        f["lat"]=b.lat + ((f["y"]+f["h"]/2)/1024-.5)*(b.radius_km/111.32)*2
        f["lon"]=b.lon + ((f["x"]+f["w"]/2)/1024-.5)*(b.radius_km/(111.32*max(.1,math.cos(math.radians(b.lat)))))*2

    geojson={"type":"FeatureCollection","features":[]}
    for f in feats:
        lat,lon=f["lat"],f["lon"]
        dy=(f["h"]/1024)*(b.radius_km/111.32)*2
        dx=(f["w"]/1024)*(b.radius_km/(111.32*max(.1,math.cos(math.radians(b.lat)))))*2
        geojson["features"].append({
            "type":"Feature","properties":f,
            "geometry":{"type":"Polygon","coordinates":[[
                [lon-dx/2,lat-dy/2],[lon+dx/2,lat-dy/2],
                [lon+dx/2,lat+dy/2],[lon-dx/2,lat+dy/2],
                [lon-dx/2,lat-dy/2]
            ]]}
        })

    return {
        "before":{"id":b.before_id,"datetime":before["properties"].get("datetime"),"bbox":before.get("bbox"),"preview":f"/api/cache/{before_file}"},
        "after":{"id":b.after_id,"datetime":after["properties"].get("datetime"),"bbox":after.get("bbox"),"preview":f"/api/cache/{after_file}"},
        "mask":f"/api/cache/{mask_file}",
        "changes":feats,
        "geojson":geojson,
        "threshold":round(threshold,2),
        "ndvi":ndvi_info,
        "semantic":semantic(b.query,feats,ndvi_info),
        "method":"Sentinel-2 L2A RGB temporal comparison + ECC registration + robust thresholding + morphology + connected components + NDVI",
        "query":b.query
    }

@app.get("/api/cache/{name}")
def cache_file(name:str):
    p=CACHE/Path(name).name
    if not p.exists(): raise HTTPException(404,"Not found")
    return FileResponse(p)

@app.get("/api/export/{kind}")
def export(kind:str):
    # The frontend passes its current GeoJSON as a data URL only for browser download;
    # this endpoint provides a minimal human-readable report.
    if kind=="report":
        html="""<!doctype html><html><head><meta charset=utf-8><title>GeoSentinel AI Report</title>
        <style>body{font:15px Arial;max-width:900px;margin:40px auto;color:#17324d}h1{font-size:30px}.box{padding:16px;background:#f2f6f8;border-left:4px solid #355c7d}</style></head>
        <body><h1>GeoSentinel AI — Change Detection Report</h1>
        <p><b>Source:</b> Sentinel-2 L2A via Microsoft Planetary Computer STAC.</p>
        <div class=box><b>Review requirement:</b> Results are candidate change signals. An authorized human analyst should validate them before operational use.</div>
        <h2>Pipeline</h2><p>Scene search → image retrieval → alignment → temporal difference → morphology → connected components → NDVI → semantic ranking → GIS visualization.</p>
        </body></html>"""
        return HTMLResponse(html)
    raise HTTPException(404,"Unknown export")

@app.get("/api/timeline")
def timeline():
    return {"description":"Use the selected before/after scenes returned by /api/search as temporal points."}
