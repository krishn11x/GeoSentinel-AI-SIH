# GeoSentinel AI — SIH-grade real Earth-observation prototype

This build replaces mock UI data with a real geospatial pipeline.

## Real data
The application searches the Microsoft Planetary Computer public STAC catalog for Sentinel-2 L2A scenes. The STAC API supports spatial, temporal and cloud-cover filtering. The backend then uses the scene's rendered preview and signed band assets.

## Features
- Real Sentinel-2 scene discovery
- Search by lat/lon/radius/date/cloud cover
- Real satellite RGB previews
- Real before/after comparison
- Temporal image registration
- Pixel-level change detection
- Morphological filtering and connected components
- NDVI vegetation change
- Natural-language semantic scoring with CLIP
- Real Leaflet GIS map
- Change polygons/boxes rendered on map
- Time slider for available scenes
- Scene metadata
- GeoJSON export of detected regions
- HTML report generation
- Demo locations for Delhi, Mumbai and Bengaluru
- Clear prototype/analyst-review disclaimer

## Run

### Backend
```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173

## First analysis
1. Select a demo location or enter coordinates.
2. Search BEFORE.
3. Search AFTER.
4. Select one scene in each period.
5. Run the semantic change analysis.
6. Use the map, comparison, semantic ranking, NDVI, timeline and export controls.

## Notes
Sentinel-2 is medium-resolution Earth observation. It is excellent for regional/land-cover/infrastructure change monitoring but cannot reliably identify small objects. Clouds, haze, seasonal vegetation, illumination and imperfect registration can create false positives.

For an SIH prototype, this is intentionally transparent: detected regions are candidates for analyst review, not ground truth.

Defence positioning should be described as authorized geospatial monitoring, mapping and decision support rather than autonomous targeting.
