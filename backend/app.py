from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from datetime import date, datetime
from pathlib import Path

import cv2
import numpy as np
import requests
import rasterio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds


# ============================================================
# CONFIG
# ============================================================

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)

ANALYSIS_CACHE = CACHE / "analysis_cache"
ANALYSIS_CACHE.mkdir(exist_ok=True)

ANALYSIS_SIZE = 512

SESSION = requests.Session()


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="GeoSentinel AI",
    version="2.2"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# MODELS
# ============================================================

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


# ============================================================
# GEO HELPERS
# ============================================================

def make_bbox(lat: float, lon: float, km: float):
    dlat = km / 111.32

    dlon = km / (
        111.32 *
        max(
            0.1,
            math.cos(math.radians(lat))
        )
    )

    return [
        lon - dlon,
        lat - dlat,
        lon + dlon,
        lat + dlat
    ]


def seasonal_similarity(
    before_datetime,
    after_datetime
):
    """
    Compare acquisition dates using month/day proximity.

    This is only a warning signal. It does not determine
    whether two scenes are scientifically comparable.
    """

    if not before_datetime or not after_datetime:
        return {
            "score": None,
            "warning": False,
            "message": None
        }

    try:
        before = datetime.fromisoformat(
            before_datetime.replace("Z", "+00:00")
        )

        after = datetime.fromisoformat(
            after_datetime.replace("Z", "+00:00")
        )

        before_day = before.timetuple().tm_yday
        after_day = after.timetuple().tm_yday

        diff = abs(
            before_day - after_day
        )

        # Handle wrap-around at year boundary.
        diff = min(
            diff,
            365 - diff
        )

        score = max(
            0.0,
            1.0 - diff / 182.5
        )

        if diff <= 30:
            message = (
                "Good seasonal match. "
                "Acquisition windows are broadly comparable."
            )
            warning = False

        elif diff <= 75:
            message = (
                "Moderate seasonal difference. "
                "Vegetation and illumination may affect change signals."
            )
            warning = True

        else:
            message = (
                "Low seasonal similarity. "
                "Vegetation, illumination and atmospheric differences "
                "may increase false positives."
            )
            warning = True

        return {
            "score": round(score, 3),
            "day_difference": diff,
            "warning": warning,
            "message": message
        }

    except Exception:
        return {
            "score": None,
            "warning": False,
            "message": None
        }


# ============================================================
# HTTP
# ============================================================

def get_json(url, **kwargs):

    response = SESSION.get(
        url,
        timeout=90,
        **kwargs
    )

    response.raise_for_status()

    return response.json()


def post_json(url, payload):

    response = SESSION.post(
        url,
        json=payload,
        timeout=90
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():

    return {
        "ok": True,
        "data_source":
            "Microsoft Planetary Computer / Sentinel-2 L2A",
        "analysis_mode":
            "AOI windowed raster processing",
        "analysis_size":
            ANALYSIS_SIZE,
        "caching":
            True
    }


# ============================================================
# SEARCH
# ============================================================

@app.post("/api/search")
def search(b: SearchBody):

    print(
        "\n[SEARCH] Searching Sentinel-2 scenes...",
        flush=True
    )

    aoi_bbox = make_bbox(
        b.lat,
        b.lon,
        b.radius_km
    )

    payload = {

        "collections": [
            "sentinel-2-l2a"
        ],

        "bbox":
            aoi_bbox,

        "datetime":
            f"{b.start}T00:00:00Z/"
            f"{b.end}T23:59:59Z",

        "limit":
            24,

        "query": {
            "eo:cloud_cover": {
                "lt": b.cloud
            }
        },

        "sortby": [
            {
                "field": "datetime",
                "direction": "desc"
            }
        ]
    }

    try:

        data = post_json(
            f"{STAC}/search",
            payload
        )

    except Exception as e:

        print(
            f"[SEARCH ERROR] {e}",
            flush=True
        )

        raise HTTPException(
            502,
            f"STAC search failed: {e}"
        )

    output = []

    for scene in data.get(
        "features",
        []
    ):

        properties = scene.get(
            "properties",
            {}
        )

        assets = scene.get(
            "assets",
            {}
        )

        preview = (

            assets.get(
                "rendered_preview"
            )

            or

            assets.get(
                "thumbnail"
            )

            or {}

        ).get("href")

        output.append({

            "id":
                scene["id"],

            "datetime":
                properties.get(
                    "datetime"
                ),

            "cloud":
                properties.get(
                    "eo:cloud_cover"
                ),

            "bbox":
                scene.get("bbox"),

            "geometry":
                scene.get("geometry"),

            "preview":
                preview,

            "assets":
                list(
                    assets.keys()
                )

        })

    print(
        f"[SEARCH] Found {len(output)} scenes",
        flush=True
    )

    return {
        "scenes":
            output,
        "bbox":
            aoi_bbox,
        "query":
            payload
    }


# ============================================================
# STAC ITEM
# ============================================================

def get_item(item_id: str):

    print(
        f"[ITEM] Loading metadata: {item_id}",
        flush=True
    )

    return get_json(
        f"{STAC}/collections/"
        f"sentinel-2-l2a/items/{item_id}"
    )


# ============================================================
# ASSET SIGNING
# ============================================================

def sign_asset(href: str):

    if "blob.core.windows.net" not in href:
        return href

    print(
        "[ASSET] Signing Planetary Computer asset...",
        flush=True
    )

    data = get_json(
        SAS,
        params={
            "href":
                href
        }
    )

    return data["href"]


# ============================================================
# REMOTE AOI WINDOW
# ============================================================

def read_band_window(
    item_data,
    band_name,
    aoi_bbox,
    size=ANALYSIS_SIZE
):

    asset = (
        item_data
        .get("assets", {})
        .get(band_name)
    )

    if not asset:

        print(
            f"[BAND] {band_name} unavailable",
            flush=True
        )

        return None

    href = sign_asset(
        asset["href"]
    )

    print(
        f"[BAND] Reading AOI only: {band_name}",
        flush=True
    )

    try:

        with rasterio.Env(

            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",

            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=
                ".tif,.TIF",

            GDAL_HTTP_TIMEOUT="60",

            GDAL_HTTP_CONNECTTIMEOUT="20",

            VSI_CACHE="TRUE",

            VSI_CACHE_SIZE="5000000"

        ):

            with rasterio.open(
                href
            ) as dataset:

                projected_bounds = transform_bounds(

                    "EPSG:4326",

                    dataset.crs,

                    *aoi_bbox,

                    densify_pts=21
                )

                window = from_bounds(

                    *projected_bounds,

                    transform=
                        dataset.transform

                )

                window = (
                    window
                    .round_offsets()
                    .round_lengths()
                )

                full_window = (
                    rasterio.windows.Window(
                        0,
                        0,
                        dataset.width,
                        dataset.height
                    )
                )

                raster_window = (
                    window.intersection(
                        full_window
                    )
                )

                if (
                    raster_window.width <= 0
                    or
                    raster_window.height <= 0
                ):

                    raise ValueError(
                        f"AOI does not intersect "
                        f"{band_name}"
                    )

                data = dataset.read(

                    1,

                    window=raster_window,

                    out_shape=(
                        size,
                        size
                    ),

                    resampling=
                        Resampling.bilinear

                ).astype(
                    np.float32
                )

                return data

    except Exception as e:

        print(
            f"[BAND ERROR] {band_name}: {e}",
            flush=True
        )

        raise


# ============================================================
# NORMALIZATION
# ============================================================

def stretch(array):

    valid = array[
        array > 0
    ]

    if valid.size == 0:

        return np.zeros_like(
            array,
            dtype=np.float32
        )

    low = np.percentile(
        valid,
        2
    )

    high = np.percentile(
        valid,
        98
    )

    normalized = (

        array - low

    ) / max(

        high - low,

        1e-6

    )

    return np.clip(
        normalized,
        0,
        1
    )


# ============================================================
# LOAD SCENE
# ============================================================

def load_scene_data(
    item_data,
    aoi_bbox
):

    print(
        "\n[SCENE] Loading analysis bands...",
        flush=True
    )

    red = read_band_window(
        item_data,
        "B04",
        aoi_bbox
    )

    green = read_band_window(
        item_data,
        "B03",
        aoi_bbox
    )

    blue = read_band_window(
        item_data,
        "B02",
        aoi_bbox
    )

    nir = read_band_window(
        item_data,
        "B08",
        aoi_bbox
    )

    if any(
        value is None
        for value in [
            red,
            green,
            blue
        ]
    ):

        raise ValueError(
            "Required RGB assets unavailable"
        )

    rgb = (

        np.stack(

            [
                stretch(red),
                stretch(green),
                stretch(blue)
            ],

            axis=-1

        )

        * 255

    ).astype(
        np.uint8
    )

    ndvi = None

    if nir is not None:

        ndvi = (

            nir - red

        ) / (

            nir + red + 1e-6

        )

    return {

        "rgb":
            rgb,

        "ndvi":
            ndvi
    }


# ============================================================
# CHANGE DETECTION
# ============================================================

def align_and_change(
    before_rgb,
    after_rgb
):

    print(
        "[PROCESS] Aligning imagery...",
        flush=True
    )

    before_gray = cv2.cvtColor(
        before_rgb,
        cv2.COLOR_RGB2GRAY
    )

    after_gray = cv2.cvtColor(
        after_rgb,
        cv2.COLOR_RGB2GRAY
    )

    warp = np.eye(
        2,
        3,
        dtype=np.float32
    )

    aligned_before = before_gray

    try:

        criteria = (

            cv2.TERM_CRITERIA_EPS
            |
            cv2.TERM_CRITERIA_COUNT,

            100,

            1e-5

        )

        cv2.findTransformECC(

            before_gray,

            after_gray,

            warp,

            cv2.MOTION_AFFINE,

            criteria

        )

        aligned_before = cv2.warpAffine(

            before_gray,

            warp,

            (
                after_gray.shape[1],
                after_gray.shape[0]
            ),

            flags=(
                cv2.INTER_LINEAR
                |
                cv2.WARP_INVERSE_MAP
            )

        )

        print(
            "[PROCESS] ECC alignment successful",
            flush=True
        )

    except cv2.error:

        print(
            "[PROCESS] ECC alignment skipped",
            flush=True
        )

    print(
        "[PROCESS] Detecting temporal change...",
        flush=True
    )

    difference = cv2.absdiff(
        aligned_before,
        after_gray
    )

    median = float(
        np.median(
            difference
        )
    )

    mad = float(

        np.median(

            np.abs(
                difference - median
            )

        )

    ) + 1

    threshold = max(
        18,
        median + 3.0 * mad
    )

    mask = (

        difference > threshold

    ).astype(
        np.uint8
    ) * 255

    kernel = np.ones(
        (7, 7),
        np.uint8
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        kernel
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        kernel
    )

    print(
        "[PROCESS] Extracting change regions...",
        flush=True
    )

    count, labels, stats, centroids = (

        cv2.connectedComponentsWithStats(
            mask
        )

    )

    features = []

    for i in range(
        1,
        count
    ):

        x, y, w, h, area = map(
            int,
            stats[i]
        )

        if area < 180:
            continue

        confidence = min(
            0.99,
            0.55 + area / 25000
        )

        features.append({

            "id":
                len(features) + 1,

            "x":
                x,

            "y":
                y,

            "w":
                w,

            "h":
                h,

            "area_px":
                area,

            "confidence":
                round(
                    confidence,
                    3
                )

        })

    return (
        mask,
        features,
        float(threshold)
    )


# ============================================================
# SEMANTIC RANKING
# ============================================================

def semantic(
    query,
    change_features,
    ndvi_info
):

    query = query.lower()

    concepts = [

        (
            "New construction",

            [
                "building",
                "construction",
                "structure",
                "infrastructure"
            ]
        ),

        (
            "Road expansion",

            [
                "road",
                "highway",
                "transport"
            ]
        ),

        (
            "Vegetation change",

            [
                "vegetation",
                "forest",
                "crop",
                "agriculture",
                "green"
            ]
        ),

        (
            "Water change",

            [
                "water",
                "lake",
                "river",
                "reservoir"
            ]
        ),

        (
            "Bare/exposed land",

            [
                "soil",
                "bare",
                "land",
                "excavation"
            ]
        ),

        (
            "Industrial infrastructure",

            [
                "industrial",
                "factory",
                "facility"
            ]
        )

    ]

    scores = []

    for label, words in concepts:

        hits = sum(

            1
            for word in words
            if word in query

        )

        score = (
            0.22
            +
            0.12 * hits
        )

        if (
            ndvi_info
            and
            label ==
                "Vegetation change"
        ):

            score += min(

                0.32,

                abs(
                    ndvi_info[
                        "mean_delta"
                    ]
                ) * 1.8
            )

        if label in (

            "New construction",
            "Road expansion",
            "Industrial infrastructure"

        ):

            score += min(

                0.28,

                len(
                    change_features
                ) / 35

            )

        scores.append({

            "label":
                label,

            "score":
                round(
                    min(
                        0.96,
                        score
                    ),
                    3
                )

        })

    return sorted(

        scores,

        key=lambda x:
            x["score"],

        reverse=True

    )


# ============================================================
# FILE SAVING
# ============================================================

def save_image(
    name,
    image
):

    path = CACHE / name

    from PIL import Image

    Image.fromarray(
        image
    ).save(path)

    return path.name


# ============================================================
# ANALYSIS CACHE
# ============================================================

def analysis_cache_key(
    before_id,
    after_id,
    query,
    lat,
    lon,
    radius_km
):

    payload = {

        "before":
            before_id,

        "after":
            after_id,

        "query":
            query.strip().lower(),

        "lat":
            round(lat, 6),

        "lon":
            round(lon, 6),

        "radius_km":
            round(radius_km, 3),

        "size":
            ANALYSIS_SIZE,

        "version":
            "2.2"

    }

    raw = json.dumps(
        payload,
        sort_keys=True
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def cache_path(key):

    return (
        ANALYSIS_CACHE
        /
        f"{key}.json"
    )


def load_cached_analysis(key):

    path = cache_path(key)

    if not path.exists():
        return None

    try:

        with path.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        # Make sure generated images still exist.
        required = [

            data
            .get("before", {})
            .get("preview", ""),

            data
            .get("after", {})
            .get("preview", ""),

            data.get("mask", "")

        ]

        for url in required:

            filename = (
                Path(url).name
            )

            if not (
                CACHE / filename
            ).exists():

                print(
                    "[CACHE] Image missing; "
                    "recomputing.",
                    flush=True
                )

                return None

        return data

    except Exception as e:

        print(
            f"[CACHE] Invalid cache: {e}",
            flush=True
        )

        return None


def save_cached_analysis(
    key,
    result
):

    path = cache_path(key)

    temp_path = path.with_suffix(
        ".tmp"
    )

    with temp_path.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file
        )

    temp_path.replace(path)


# ============================================================
# ANALYZE
# ============================================================

@app.post("/api/analyze")
def analyze(
    b: AnalyzeBody
):

    start_time = time.perf_counter()

    print(
        "\n" + "=" * 60,
        flush=True
    )

    print(
        "[ANALYSIS] GeoSentinel analysis started",
        flush=True
    )

    print(
        f"[ANALYSIS] BEFORE: {b.before_id}",
        flush=True
    )

    print(
        f"[ANALYSIS] AFTER:  {b.after_id}",
        flush=True
    )

    # --------------------------------------------------------
    # CACHE CHECK
    # --------------------------------------------------------

    key = analysis_cache_key(

        b.before_id,
        b.after_id,
        b.query,
        b.lat,
        b.lon,
        b.radius_km

    )

    cached = load_cached_analysis(
        key
    )

    if cached is not None:

        cached["cache"] = {
            "hit": True,
            "key": key
        }

        elapsed = (
            time.perf_counter()
            -
            start_time
        )

        print(
            f"[CACHE HIT] Returning cached "
            f"analysis in {elapsed:.2f}s",
            flush=True
        )

        print(
            "=" * 60 + "\n",
            flush=True
        )

        return cached

    print(
        "[CACHE MISS] Running new analysis",
        flush=True
    )

    try:

        # ----------------------------------------------------
        # AOI
        # ----------------------------------------------------

        aoi_bbox = make_bbox(
            b.lat,
            b.lon,
            b.radius_km
        )

        print(
            f"[ANALYSIS] AOI: {aoi_bbox}",
            flush=True
        )

        # ----------------------------------------------------
        # METADATA
        # ----------------------------------------------------

        before_item = get_item(
            b.before_id
        )

        after_item = get_item(
            b.after_id
        )

        before_datetime = (
            before_item
            .get("properties", {})
            .get("datetime")
        )

        after_datetime = (
            after_item
            .get("properties", {})
            .get("datetime")
        )

        seasonal = seasonal_similarity(
            before_datetime,
            after_datetime
        )

        if seasonal["warning"]:

            print(
                "[WARNING] " +
                seasonal["message"],
                flush=True
            )

        # ----------------------------------------------------
        # BEFORE
        # ----------------------------------------------------

        print(
            "\n[ANALYSIS] Loading BEFORE AOI...",
            flush=True
        )

        before_data = load_scene_data(

            before_item,

            aoi_bbox

        )

        # ----------------------------------------------------
        # AFTER
        # ----------------------------------------------------

        print(
            "\n[ANALYSIS] Loading AFTER AOI...",
            flush=True
        )

        after_data = load_scene_data(

            after_item,

            aoi_bbox

        )

        before_rgb = (
            before_data["rgb"]
        )

        after_rgb = (
            after_data["rgb"]
        )

        # ----------------------------------------------------
        # CHANGE
        # ----------------------------------------------------

        mask, features, threshold = (

            align_and_change(

                before_rgb,
                after_rgb

            )

        )

        # ----------------------------------------------------
        # NDVI
        # ----------------------------------------------------

        print(
            "[PROCESS] Calculating NDVI...",
            flush=True
        )

        before_ndvi = (
            before_data["ndvi"]
        )

        after_ndvi = (
            after_data["ndvi"]
        )

        ndvi_info = None

        if (
            before_ndvi is not None
            and
            after_ndvi is not None
        ):

            delta = (
                after_ndvi
                -
                before_ndvi
            )

            ndvi_info = {

                "mean_delta":
                    round(
                        float(
                            np.mean(delta)
                        ),
                        4
                    ),

                "loss_fraction":
                    round(
                        float(
                            np.mean(
                                delta < -0.15
                            )
                        ),
                        4
                    ),

                "gain_fraction":
                    round(
                        float(
                            np.mean(
                                delta > 0.15
                            )
                        ),
                        4
                    )

            }

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        print(
            "[PROCESS] Saving outputs...",
            flush=True
        )

        before_file = save_image(

            f"{uuid.uuid4()}_before.jpg",

            before_rgb

        )

        after_file = save_image(

            f"{uuid.uuid4()}_after.jpg",

            after_rgb

        )

        mask_file = save_image(

            f"{uuid.uuid4()}_mask.png",

            mask

        )

        # ----------------------------------------------------
        # MAP COORDINATES
        # ----------------------------------------------------

        for feature in features:

            feature["lat"] = (

                b.lat

                +

                (

                    (
                        feature["y"]
                        +
                        feature["h"] / 2
                    )
                    /
                    ANALYSIS_SIZE
                    -
                    0.5

                )

                *

                (
                    b.radius_km
                    /
                    111.32
                )

                *
                2

            )

            feature["lon"] = (

                b.lon

                +

                (

                    (
                        feature["x"]
                        +
                        feature["w"] / 2
                    )
                    /
                    ANALYSIS_SIZE
                    -
                    0.5

                )

                *

                (

                    b.radius_km
                    /
                    (
                        111.32
                        *
                        max(
                            0.1,
                            math.cos(
                                math.radians(
                                    b.lat
                                )
                            )
                        )
                    )

                )

                *
                2

            )

        # ----------------------------------------------------
        # GEOJSON
        # ----------------------------------------------------

        geojson = {

            "type":
                "FeatureCollection",

            "features":
                []

        }

        for feature in features:

            lat = feature["lat"]

            lon = feature["lon"]

            dy = (

                feature["h"]
                /
                ANALYSIS_SIZE

            ) * (

                b.radius_km
                /
                111.32

            ) * 2

            dx = (

                feature["w"]
                /
                ANALYSIS_SIZE

            ) * (

                b.radius_km
                /
                (
                    111.32
                    *
                    max(
                        0.1,
                        math.cos(
                            math.radians(
                                b.lat
                            )
                        )
                    )
                )

            ) * 2

            geojson[
                "features"
            ].append({

                "type":
                    "Feature",

                "properties":
                    feature,

                "geometry": {

                    "type":
                        "Polygon",

                    "coordinates": [[

                        [
                            lon - dx / 2,
                            lat - dy / 2
                        ],

                        [
                            lon + dx / 2,
                            lat - dy / 2
                        ],

                        [
                            lon + dx / 2,
                            lat + dy / 2
                        ],

                        [
                            lon - dx / 2,
                            lat + dy / 2
                        ],

                        [
                            lon - dx / 2,
                            lat - dy / 2
                        ]

                    ]]

                }

            })

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        result = {

            "before": {

                "id":
                    b.before_id,

                "datetime":
                    before_datetime,

                "bbox":
                    before_item.get(
                        "bbox"
                    ),

                "preview":
                    f"/api/cache/{before_file}"

            },

            "after": {

                "id":
                    b.after_id,

                "datetime":
                    after_datetime,

                "bbox":
                    after_item.get(
                        "bbox"
                    ),

                "preview":
                    f"/api/cache/{after_file}"

            },

            "mask":
                f"/api/cache/{mask_file}",

            "changes":
                features,

            "geojson":
                geojson,

            "threshold":
                round(
                    threshold,
                    2
                ),

            "ndvi":
                ndvi_info,

            "semantic":
                semantic(
                    b.query,
                    features,
                    ndvi_info
                ),

            "seasonal_similarity":
                seasonal,

            "method":
                "Sentinel-2 L2A AOI windowed RGB "
                "temporal comparison + ECC registration + "
                "robust thresholding + morphology + "
                "connected components + NDVI",

            "query":
                b.query,

            "cache": {

                "hit":
                    False,

                "key":
                    key

            }

        }

        # ----------------------------------------------------
        # SAVE CACHE
        # ----------------------------------------------------

        save_cached_analysis(
            key,
            result
        )

        elapsed = (
            time.perf_counter()
            -
            start_time
        )

        print(
            f"[ANALYSIS COMPLETE] "
            f"{len(features)} candidate regions "
            f"in {elapsed:.2f}s",
            flush=True
        )

        print(
            "[CACHE] Analysis saved.",
            flush=True
        )

        print(
            "=" * 60 + "\n",
            flush=True
        )

        return result

    except HTTPException:

        raise

    except Exception as e:

        print(
            "\n[ANALYSIS ERROR] "
            f"{type(e).__name__}: {e}",
            flush=True
        )

        print(
            "=" * 60 + "\n",
            flush=True
        )

        raise HTTPException(

            status_code=500,

            detail=(
                "Satellite analysis failed: "
                f"{type(e).__name__}: {e}"
            )

        )


# ============================================================
# CACHE FILES
# ============================================================

@app.get("/api/cache/{name}")
def cache_file(name: str):

    path = (
        CACHE
        /
        Path(name).name
    )

    if not path.exists():

        raise HTTPException(
            404,
            "Not found"
        )

    return FileResponse(
        path
    )


# ============================================================
# REPORT
# ============================================================

@app.get("/api/export/{kind}")
def export(kind: str):

    if kind == "report":

        html = """
<!doctype html>

<html>

<head>

<meta charset="utf-8">

<title>GeoSentinel AI Report</title>

<style>

body{
    font:15px Arial;
    max-width:900px;
    margin:40px auto;
    color:#17324d
}

h1{
    font-size:30px
}

.box{
    padding:16px;
    background:#f2f6f8;
    border-left:4px solid #355c7d
}

.warn{
    padding:16px;
    background:#fff7e6;
    border-left:4px solid #b7791f
}

</style>

</head>

<body>

<h1>
GeoSentinel AI — Change Detection Report
</h1>

<p>
<b>Source:</b>
Sentinel-2 L2A via Microsoft Planetary Computer STAC.
</p>

<div class="box">

<b>Review requirement:</b>

Results are candidate change signals.

An authorized human analyst should validate them
before operational use.

</div>

<div class="warn">

<b>Method limitation:</b>

Sentinel-2 is medium-resolution imagery. Seasonal,
cloud, haze, illumination and registration differences
may produce false positives.

</div>

<h2>Pipeline</h2>

<p>

Scene search
→ AOI raster retrieval
→ alignment
→ temporal difference
→ morphology
→ connected components
→ NDVI
→ semantic ranking
→ GIS visualization.

</p>

</body>

</html>
"""

        return HTMLResponse(
            html
        )

    raise HTTPException(
        404,
        "Unknown export"
    )


# ============================================================
# TIMELINE
# ============================================================

@app.get("/api/timeline")
def timeline():

    return {

        "description":
            "Use selected before/after scenes returned "
            "by /api/search as temporal points."

    }