import React,{useEffect,useMemo,useState} from "react";
import {createRoot} from "react-dom/client";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./styles.css";

const API="http://127.0.0.1:8000";
const presets={
 "Delhi, India":[28.6139,77.2090],
 "Mumbai, India":[19.0760,72.8777],
 "Bengaluru, India":[12.9716,77.5946]
};

function Map({lat,lon,changes}){
 useEffect(()=>{
  const map=L.map("map").setView([lat,lon],12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{attribution:"© OpenStreetMap contributors"}).addTo(map);
  L.marker([lat,lon]).addTo(map).bindPopup("GeoSentinel analysis AOI").openPopup();
  changes.forEach(c=>L.rectangle([[c.lat-.002,c.lon-.002],[c.lat+.002,c.lon+.002]],{weight:2}).addTo(map).bindPopup(`Change #${c.id} · ${(c.confidence*100).toFixed(0)}%`));
  return()=>map.remove();
 },[lat,lon,JSON.stringify(changes)]);
 return <div id="map" className="map"/>
}

function App(){
 const [place,setPlace]=useState("Delhi, India"),[lat,setLat]=useState(28.6139),[lon,setLon]=useState(77.2090);
 const [radius,setRadius]=useState(5),[cloud,setCloud]=useState(15);
 const [bs,setBs]=useState("2020-01-01"),[be,setBe]=useState("2020-03-31");
 const [as,setAs]=useState("2026-01-01"),[ae,setAe]=useState("2026-03-31");
 const [before,setBefore]=useState([]),[after,setAfter]=useState([]),[bid,setBid]=useState(""),[aid,setAid]=useState("");
 const [query,setQuery]=useState("Identify newly constructed infrastructure and road expansion");
 const [result,setResult]=useState(null),[busy,setBusy]=useState(false),[err,setErr]=useState("");

 function preset(v){setPlace(v);setLat(presets[v][0]);setLon(presets[v][1])}
 async function search(period){
  setBusy(true);setErr("");
  const body={lat:+lat,lon:+lon,radius_km:+radius,start:period==="before"?bs:as,end:period==="before"?be:ae,cloud:+cloud};
  try{const r=await fetch(`${API}/api/search`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});if(!r.ok)throw Error(await r.text());const d=await r.json();period==="before"?setBefore(d.scenes):setAfter(d.scenes)}
  catch(e){setErr(e.message)}finally{setBusy(false)}
 }
 async function analyze(){
  if(!bid||!aid){setErr("Select a real scene from both periods.");return}
  setBusy(true);setErr("");
  try{const r=await fetch(`${API}/api/analyze`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({before_id:bid,after_id:aid,query,lat:+lat,lon:+lon,radius_km:+radius})});if(!r.ok)throw Error(await r.text());setResult(await r.json())}
  catch(e){setErr(e.message)}finally{setBusy(false)}
 }
 function downloadGeo(){if(!result)return;const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(result.geojson,null,2)],{type:"application/geo+json"}));a.download="geosentinel-changes.geojson";a.click()}
 return <><header><div className="logo">GEOSENTINEL <span>AI</span></div><nav>REAL SATELLITE INTELLIGENCE · SIH 2026</nav><div className="live">● LIVE DATA</div></header>
 <main>
 <section className="hero"><div><div className="eyebrow">EARTH OBSERVATION · TEMPORAL CHANGE DETECTION</div><h1>See what changed.<br/><span>Understand the landscape.</span></h1><p>Search real Sentinel-2 imagery, compare dates, detect spatial change, query the imagery in natural language and inspect results on a GIS map.</p></div><div className="source"><b>DATA SOURCE</b><strong>Sentinel-2 L2A</strong><small>Microsoft Planetary Computer STAC</small><small>Public Earth-observation data</small></div></section>

 <section className="workspace">
 <aside><div className="step active">01 <b>Area & imagery</b></div><div className="step">02 <b>Semantic query</b></div><div className="step">03 <b>Change analysis</b></div><div className="step">04 <b>GIS results</b></div><div className="side-note">Prototype data is real satellite imagery. Results are candidate changes and require analyst validation.</div></aside>
 <div className="content">
 <section className="card"><div className="head"><h2>Define Area of Interest</h2><span>REAL STAC SEARCH</span></div>
 <div className="preset">{Object.keys(presets).map(x=><button className={place===x?"chosen":""} onClick={()=>preset(x)} key={x}>{x}</button>)}</div>
 <div className="fields"><label>Location<input value={place} onChange={e=>setPlace(e.target.value)}/></label><label>Latitude<input value={lat} onChange={e=>setLat(e.target.value)}/></label><label>Longitude<input value={lon} onChange={e=>setLon(e.target.value)}/></label><label>Radius km<input value={radius} onChange={e=>setRadius(e.target.value)}/></label><label>Max cloud %<input value={cloud} onChange={e=>setCloud(e.target.value)}/></label></div>
 </section>

 <div className="period-grid"><Period title="BEFORE" start={bs} end={be} setStart={setBs} setEnd={setBe} scenes={before} selected={bid} select={setBid} search={()=>search("before")}/><Period title="AFTER" start={as} end={ae} setStart={setAs} setEnd={setAe} scenes={after} selected={aid} select={setAid} search={()=>search("after")}/></div>

 <section className="card"><div className="head"><h2>Semantic Search</h2><span>NATURAL LANGUAGE</span></div><textarea value={query} onChange={e=>setQuery(e.target.value)}/><div className="chips">{["new construction","road expansion","vegetation loss","water change","industrial infrastructure"].map(x=><button onClick={()=>setQuery(`Identify ${x} between the selected dates.`)} key={x}>{x}</button>)}</div><button className="run" onClick={analyze} disabled={busy}>{busy?"PROCESSING SATELLITE DATA…":"RUN REAL CHANGE ANALYSIS →"}</button></section>

 {err&&<div className="error">{err}</div>}
 {result&&<Results result={result} lat={+lat} lon={+lon} download={downloadGeo}/>}
 </div></section></main>
 <footer>GeoSentinel AI · Real Sentinel-2 data · Authorized geospatial monitoring & decision support</footer></>
}

function Period({title,start,end,setStart,setEnd,scenes,selected,select,search}){
 return <section className="period card"><div className="head"><h2>{title}</h2><span>{scenes.length} SCENES</span></div><div className="dates"><input type="date" value={start} onChange={e=>setStart(e.target.value)}/><span>→</span><input type="date" value={end} onChange={e=>setEnd(e.target.value)}/></div><button className="search" onClick={search}>SEARCH REAL SATELLITE SCENES</button><div className="scene-list">{scenes.map(s=><button className={"scene "+(selected===s.id?"sel":"")} onClick={()=>select(s.id)} key={s.id}><img src={s.preview}/><span><b>{s.datetime?.slice(0,10)}</b><small>{Number(s.cloud||0).toFixed(1)}% cloud</small><small>{s.id}</small></span></button>)}</div></section>
}

function Results({result,lat,lon,download}){
 const [tab,setTab]=useState("overview"),[t,setT]=useState(50);
 const score=result.semantic||[];
 return <section className="results">
  <div className="result-top"><div><div className="eyebrow">ANALYSIS COMPLETE</div><h2>{result.changes.length} candidate change regions detected</h2><p>Threshold: {result.threshold} · {result.method}</p></div><div className="actions"><button onClick={download}>Export GeoJSON</button><a href={`${API}/api/export/report`} target="_blank">Report</a></div></div>
  <div className="tabs">{["overview","comparison","semantic","map","data"].map(x=><button className={tab===x?"on":""} onClick={()=>setTab(x)} key={x}>{x}</button>)}</div>
  {tab==="overview"&&<><div className="kpis"><K n={result.changes.length} t="Change regions"/><K n={result.ndvi?`${(result.ndvi.loss_fraction*100).toFixed(1)}%`:"—"} t="Vegetation loss signal"/><K n={score[0]?`${(score[0].score*100).toFixed(0)}%`:"—"} t="Top semantic score"/><K n={result.before.datetime?.slice(0,10)} t="Before acquisition"/><K n={result.after.datetime?.slice(0,10)} t="After acquisition"/></div><div className="compare"><div><label>BEFORE</label><img src={`${API}${result.before.preview}`}/></div><div><label>AFTER</label><img src={`${API}${result.after.preview}`}/></div><div><label>CHANGE MASK</label><img src={`${API}${result.mask}`}/></div></div></>}
  {tab==="comparison"&&<div className="slider-wrap"><div className="slider-stage"><img src={`${API}${result.after.preview}`}/><div className="clip"><img src={`${API}${result.before.preview}`}/></div><input type="range" min="0" max="100" value={t} onChange={e=>setT(e.target.value)}/><span className="before-label">BEFORE</span><span className="after-label">AFTER</span></div><p>Drag the slider to inspect the real satellite acquisitions.</p></div>}
  {tab==="semantic"&&<div className="semantic">{score.map(s=><div className="sem" key={s.label}><div><b>{s.label}</b><span>{(s.score*100).toFixed(1)}%</span></div><i><u style={{width:`${s.score*100}%`}}/></i></div>)}</div>}
  {tab==="map"&&<><Map lat={lat} lon={lon} changes={result.changes}/><div className="map-meta">Each rectangle is a candidate change region derived from the real before/after imagery. Coordinates are exported as GeoJSON for further GIS work.</div></>}
  {tab==="data"&&<table><thead><tr><th>ID</th><th>Confidence</th><th>Area px</th><th>Latitude</th><th>Longitude</th></tr></thead><tbody>{result.changes.map(c=><tr key={c.id}><td>#{c.id}</td><td>{(c.confidence*100).toFixed(0)}%</td><td>{c.area_px.toLocaleString()}</td><td>{c.lat.toFixed(5)}</td><td>{c.lon.toFixed(5)}</td></tr>)}</tbody></table>}
  <div className="disclaimer">Important: medium-resolution Sentinel-2 imagery can produce false positives from clouds, haze, seasonal vegetation, shadows, illumination and registration errors. These outputs are decision-support signals, not autonomous operational determinations.</div>
 </section>
}
function K({n,t}){return <div className="kpi"><b>{n}</b><span>{t}</span></div>}
createRoot(document.getElementById("root")).render(<App/>)
