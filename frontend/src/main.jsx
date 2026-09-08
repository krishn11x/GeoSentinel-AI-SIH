import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./styles.css";

const API = "http://127.0.0.1:8000";

const presets = {
  "Delhi, India": [28.6139, 77.2090],
  "Mumbai, India": [19.0760, 72.8777],
  "Bengaluru, India": [12.9716, 77.5946]
};


// ============================================================
// MAP
// ============================================================

function Map({ lat, lon, changes }) {

  useEffect(() => {

    const map = L.map("map").setView(
      [lat, lon],
      12
    );

    L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        attribution:
          "© OpenStreetMap contributors"
      }
    ).addTo(map);

    L.marker([lat, lon])
      .addTo(map)
      .bindPopup(
        "GeoSentinel analysis AOI"
      )
      .openPopup();

    changes.forEach((c) => {

      L.rectangle(
        [
          [
            c.lat - 0.002,
            c.lon - 0.002
          ],
          [
            c.lat + 0.002,
            c.lon + 0.002
          ]
        ],
        {
          weight: 2
        }
      )
        .addTo(map)
        .bindPopup(
          `Candidate Change #${c.id} · ${(c.confidence * 100).toFixed(0)}%`
        );

    });

    return () => {
      map.remove();
    };

  }, [
    lat,
    lon,
    JSON.stringify(changes)
  ]);

  return (
    <div
      id="map"
      className="map"
    />
  );
}


// ============================================================
// MAIN APP
// ============================================================

function App() {

  const [place, setPlace] =
    useState("Delhi, India");

  const [lat, setLat] =
    useState(28.6139);

  const [lon, setLon] =
    useState(77.2090);

  const [radius, setRadius] =
    useState(5);

  const [cloud, setCloud] =
    useState(15);

  const [bs, setBs] =
    useState("2020-01-01");

  const [be, setBe] =
    useState("2020-03-31");

  const [as, setAs] =
    useState("2026-01-01");

  const [ae, setAe] =
    useState("2026-03-31");

  const [before, setBefore] =
    useState([]);

  const [after, setAfter] =
    useState([]);

  const [bid, setBid] =
    useState("");

  const [aid, setAid] =
    useState("");

  const [query, setQuery] =
    useState(
      "Identify newly constructed infrastructure and road expansion"
    );

  const [result, setResult] =
    useState(null);

  const [busy, setBusy] =
    useState(false);

  const [err, setErr] =
    useState("");

  const [progress, setProgress] =
    useState(null);


  // ==========================================================
  // PRESET LOCATION
  // ==========================================================

  function preset(value) {

    setPlace(value);

    setLat(
      presets[value][0]
    );

    setLon(
      presets[value][1]
    );

    setBefore([]);
    setAfter([]);
    setBid("");
    setAid("");
    setResult(null);
    setErr("");
  }


  // ==========================================================
  // SEARCH SATELLITE SCENES
  // ==========================================================

  async function search(period) {

    setBusy(true);
    setErr("");

    const body = {

      lat: +lat,
      lon: +lon,
      radius_km: +radius,

      start:
        period === "before"
          ? bs
          : as,

      end:
        period === "before"
          ? be
          : ae,

      cloud: +cloud

    };

    try {

      const response =
        await fetch(
          `${API}/api/search`,
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json"
            },

            body:
              JSON.stringify(body)
          }
        );

      if (!response.ok) {

        throw new Error(
          await response.text()
        );

      }

      const data =
        await response.json();

      if (period === "before") {

        setBefore(
          data.scenes
        );

        setBid("");

      } else {

        setAfter(
          data.scenes
        );

        setAid("");

      }

    } catch (error) {

      setErr(
        error.message
      );

    } finally {

      setBusy(false);

    }

  }


  // ==========================================================
  // RUN ANALYSIS
  // ==========================================================

  async function analyze() {

    if (!bid || !aid) {

      setErr(
        "Select a real scene from both periods."
      );

      return;
    }

    const analysisId =
      crypto.randomUUID();

    setBusy(true);
    setErr("");
    setResult(null);

    setProgress({

      stage:
        "starting",

      message:
        "Starting satellite analysis...",

      progress:
        5

    });


    // --------------------------------------------------------
    // STATUS POLLING
    // --------------------------------------------------------

    let polling = true;

    async function pollStatus() {

      while (polling) {

        try {

          const response =
            await fetch(
              `${API}/api/analyze/status/${analysisId}`
            );

          if (response.ok) {

            const data =
              await response.json();

            setProgress(data);

            if (
              data.stage === "complete"
              ||
              data.stage === "error"
            ) {

              break;

            }

          }

        } catch {
          // Temporary status failures are ignored.
        }

        await new Promise(
          resolve =>
            setTimeout(
              resolve,
              500
            )
        );

      }

    }

    pollStatus();


    // --------------------------------------------------------
    // ACTUAL ANALYSIS REQUEST
    // --------------------------------------------------------

    try {

      const response =
        await fetch(
          `${API}/api/analyze`,
          {

            method:
              "POST",

            headers: {
              "Content-Type":
                "application/json"
            },

            body:
              JSON.stringify({

                before_id:
                  bid,

                after_id:
                  aid,

                query:

                query,

                lat:
                  +lat,

                lon:
                  +lon,

                radius_km:
                  +radius,

                analysis_id:
                  analysisId

              })

          }
        );

      polling = false;

      if (!response.ok) {

        let message;

        try {

          const errorData =
            await response.json();

          message =
            errorData.detail ||
            JSON.stringify(
              errorData
            );

        } catch {

          message =
            await response.text();

        }

        throw new Error(
          message ||
          "Analysis request failed."
        );

      }

      const data =
        await response.json();

      setProgress({

        stage:
          "complete",

        message:
          data.cache?.hit
            ? "Cached analysis loaded."
            : "Analysis complete.",

        progress:
          100

      });

      setResult(
        data
      );

    } catch (error) {

      polling = false;

      setProgress({

        stage:
          "error",

        message:
          "Analysis failed.",

        progress:
          0

      });

      setErr(
        error.message
      );

    } finally {

      setBusy(false);

    }

  }


  // ==========================================================
  // GEOJSON DOWNLOAD
  // ==========================================================

  function downloadGeo() {

    if (!result)
      return;

    const blob =
      new Blob(
        [
          JSON.stringify(
            result.geojson,
            null,
            2
          )
        ],
        {
          type:
            "application/geo+json"
        }
      );

    const link =
      document.createElement(
        "a"
      );

    link.href =
      URL.createObjectURL(
        blob
      );

    link.download =
      "geosentinel-changes.geojson";

    link.click();

    URL.revokeObjectURL(
      link.href
    );

  }


  // ==========================================================
  // UI
  // ==========================================================

  return (
    <>
      <header>

        <div className="logo">

          GEOSENTINEL{" "}

          <span>
            AI
          </span>

        </div>

        <nav>
          REAL SATELLITE INTELLIGENCE · SIH 2026
        </nav>

        <div className="live">
          ● LIVE DATA
        </div>

      </header>


      <main>

        {/* ==================================================
            HERO
           ================================================== */}

        <section className="hero">

          <div>

            <div className="eyebrow">
              EARTH OBSERVATION · TEMPORAL CHANGE DETECTION
            </div>

            <h1>

              See what changed.

              <br />

              <span>
                Understand the landscape.
              </span>

            </h1>

            <p>
              Search real Sentinel-2 imagery,
              compare dates, detect spatial
              change, query the imagery in
              natural language and inspect
              results on a GIS map.
            </p>

          </div>


          <div className="source">

            <b>
              DATA SOURCE
            </b>

            <strong>
              Sentinel-2 L2A
            </strong>

            <small>
              Microsoft Planetary Computer STAC
            </small>

            <small>
              Public Earth-observation data
            </small>

          </div>

        </section>


        {/* ==================================================
            WORKSPACE
           ================================================== */}

        <section className="workspace">

          <aside>

            <div className="step active">

              01
              {" "}

              <b>
                Area & imagery
              </b>

            </div>


            <div className="step">

              02

              {" "}

              <b>
                Semantic query
              </b>

            </div>


            <div className="step">

              03

              {" "}

              <b>
                Change analysis
              </b>

            </div>


            <div className="step">

              04

              {" "}

              <b>
                GIS results
              </b>

            </div>


            <div className="side-note">

              Prototype data is real satellite
              imagery. Results are candidate
              changes and require analyst validation.

            </div>

          </aside>


          <div className="content">


            {/* =================================================
                AOI CARD
               ================================================= */}

            <section className="card">

              <div className="head">

                <h2>
                  Define Area of Interest
                </h2>

                <span>
                  REAL STAC SEARCH
                </span>

              </div>


              <div className="preset">

                {Object.keys(
                  presets
                ).map(value => (

                  <button

                    className={
                      place === value
                        ? "chosen"
                        : ""
                    }

                    onClick={() =>
                      preset(value)
                    }

                    key={value}

                  >

                    {value}

                  </button>

                ))}

              </div>


              <div className="fields">

                <label>

                  Location

                  <input

                    value={place}

                    onChange={e =>
                      setPlace(
                        e.target.value
                      )
                    }

                  />

                </label>


                <label>

                  Latitude

                  <input

                    value={lat}

                    onChange={e =>
                      setLat(
                        e.target.value
                      )
                    }

                  />

                </label>


                <label>

                  Longitude

                  <input

                    value={lon}

                    onChange={e =>
                      setLon(
                        e.target.value
                      )
                    }

                  />

                </label>


                <label>

                  Radius km

                  <input

                    value={radius}

                    onChange={e =>
                      setRadius(
                        e.target.value
                      )
                    }

                  />

                </label>


                <label>

                  Max cloud %

                  <input

                    value={cloud}

                    onChange={e =>
                      setCloud(
                        e.target.value
                      )
                    }

                  />

                </label>

              </div>

            </section>


            {/* =================================================
                BEFORE / AFTER
               ================================================= */}

            <div className="period-grid">

              <Period

                title="BEFORE"

                start={bs}

                end={be}

                setStart={setBs}

                setEnd={setBe}

                scenes={before}

                selected={bid}

                select={setBid}

                search={() =>
                  search("before")
                }

              />


              <Period

                title="AFTER"

                start={as}

                end={ae}

                setStart={setAs}

                setEnd={setAe}

                scenes={after}

                selected={aid}

                select={setAid}

                search={() =>
                  search("after")
                }

              />

            </div>


            {/* =================================================
                SEMANTIC SEARCH
               ================================================= */}

            <section className="card">

              <div className="head">

                <h2>
                  Semantic Search
                </h2>

                <span>
                  NATURAL LANGUAGE
                </span>

              </div>


              <textarea

                value={query}

                onChange={e =>
                  setQuery(
                    e.target.value
                  )
                }

              />


              <div className="chips">

                {[
                  "new construction",
                  "road expansion",
                  "vegetation loss",
                  "water change",
                  "industrial infrastructure"
                ].map(value => (

                  <button

                    onClick={() =>
                      setQuery(
                        `Identify ${value} between the selected dates.`
                      )
                    }

                    key={value}

                  >

                    {value}

                  </button>

                ))}

              </div>


              <button

                className="run"

                onClick={
                  analyze
                }

                disabled={
                  busy
                }

              >

                {busy

                  ? "PROCESSING SATELLITE DATA..."

                  : "RUN REAL CHANGE ANALYSIS →"}

              </button>

            </section>


            {/* =================================================
                LIVE PROGRESS
               ================================================= */}

            {busy &&
              progress && (

                <AnalysisProgress
                  progress={
                    progress
                  }
                />

              )}


            {/* =================================================
                ERROR
               ================================================= */}

            {err && (

              <div className="error">

                {err}

              </div>

            )}


            {/* =================================================
                RESULTS
               ================================================= */}

            {result && (

              <Results

                result={
                  result
                }

                lat={
                  +lat
                }

                lon={
                  +lon
                }

                download={
                  downloadGeo
                }

              />

            )}

          </div>

        </section>

      </main>


      <footer>

        GeoSentinel AI · Real Sentinel-2 data ·
        Authorized geospatial monitoring &
        decision support

      </footer>

    </>
  );
}


// ============================================================
// LIVE PROGRESS COMPONENT
// ============================================================

function AnalysisProgress({
  progress
}) {

  const stages = [

    {
      key:
        "starting",

      label:
        "Starting analysis"
    },

    {
      key:
        "aoi",

      label:
        "Preparing area of interest"
    },

    {
      key:
        "before",

      label:
        "Reading BEFORE imagery"
    },

    {
      key:
        "after",

      label:
        "Reading AFTER imagery"
    },

    {
      key:
        "change_detection",

      label:
        "Detecting temporal change"
    },

    {
      key:
        "ndvi",

      label:
        "Calculating NDVI"
    },

    {
      key:
        "results",

      label:
        "Generating GIS results"
    },

    {
      key:
        "complete",

      label:
        "Analysis complete"
    }

  ];


  const currentIndex =
    stages.findIndex(
      stage =>
        stage.key ===
        progress.stage
    );


  return (

    <section className="analysis-progress card">

      <div className="progress-header">

        <div>

          <div className="eyebrow">
            LIVE PROCESSING
          </div>

          <h2>
            Satellite analysis in progress
          </h2>

          <p>
            {progress.message}
          </p>

        </div>


        <strong>

          {progress.progress}%

        </strong>

      </div>


      <div className="progress-track">

        <div

          className="progress-fill"

          style={{
            width:
              `${progress.progress}%`
          }}

        />

      </div>


      <div className="analysis-stages">

        {stages.map(
          (stage, index) => {

            let state =
              "pending";

            if (
              currentIndex >= 0 &&
              index < currentIndex
            ) {

              state =
                "done";

            } else if (
              index === currentIndex
            ) {

              state =
                "current";

            }

            return (

              <div

                className={
                  `analysis-stage ${state}`
                }

                key={
                  stage.key
                }

              >

                <span>

                  {state === "done"

                    ? "✓"

                    : state === "current"

                    ? "●"

                    : "○"}

                </span>


                <label>

                  {stage.label}

                </label>

              </div>

            );

          }

        )}

      </div>

    </section>

  );
}


// ============================================================
// PERIOD COMPONENT
// ============================================================

function Period({
  title,
  start,
  end,
  setStart,
  setEnd,
  scenes,
  selected,
  select,
  search
}) {

  return (

    <section className="period card">

      <div className="head">

        <h2>
          {title}
        </h2>

        <span>
          {scenes.length} SCENES
        </span>

      </div>


      <div className="dates">

        <input

          type="date"

          value={
            start
          }

          onChange={e =>
            setStart(
              e.target.value
            )
          }

        />

        <span>
          →
        </span>

        <input

          type="date"

          value={
            end
          }

          onChange={e =>
            setEnd(
              e.target.value
            )
          }

        />

      </div>


      <button

        className="search"

        onClick={
          search
        }

      >

        SEARCH REAL SATELLITE SCENES

      </button>


      <div className="scene-list">

        {scenes.map(
          scene => (

            <button

              className={
                "scene " +
                (
                  selected ===
                  scene.id
                    ? "sel"
                    : ""
                )
              }

              onClick={() =>
                select(
                  scene.id
                )
              }

              key={
                scene.id
              }

            >

              <img

                src={
                  scene.preview
                }

                alt=""

              />


              <span>

                <b>

                  {
                    scene.datetime
                      ?.slice(
                        0,
                        10
                      )
                  }

                </b>


                <small>

                  {
                    Number(
                      scene.cloud ||
                      0
                    ).toFixed(1)
                  }

                  % cloud

                </small>


                <small>

                  {
                    scene.id
                  }

                </small>

              </span>

            </button>

          )
        )}

      </div>

    </section>

  );
}


// ============================================================
// RESULTS
// ============================================================

function Results({
  result,
  lat,
  lon,
  download
}) {

  const [tab, setTab] =
    useState("overview");

  const [t, setT] =
    useState(50);

  const score =
    result.semantic || [];


  return (

    <section className="results">


      {/* ======================================================
          RESULT HEADER
         ====================================================== */}

      <div className="result-top">

        <div>

          <div className="eyebrow">

            ANALYSIS COMPLETE

          </div>


          <h2>

            {
              result.changes.length
            }

            {" "}

            candidate change regions detected

          </h2>


          <p>

            Threshold:
            {" "}
            {result.threshold}

            {" · "}

            {result.method}

          </p>

        </div>


        <div className="actions">

          <button
            onClick={
              download
            }
          >
            Export GeoJSON
          </button>


          <a

            href={
              `${API}/api/export/report`
            }

            target="_blank"

            rel="noreferrer"

          >
            Report
          </a>

        </div>

      </div>


      {/* ======================================================
          TABS
         ====================================================== */}

      <div className="tabs">

        {[
          "overview",
          "comparison",
          "semantic",
          "map",
          "data"
        ].map(value => (

          <button

            className={
              tab === value
                ? "on"
                : ""
            }

            onClick={() =>
              setTab(
                value
              )
            }

            key={
              value
            }

          >

            {value}

          </button>

        ))}

      </div>


      {/* ======================================================
          OVERVIEW
         ====================================================== */}

      {tab === "overview" && (

        <>

          <div className="kpis">

            <K

              n={
                result.changes.length
              }

              t="Change regions"

            />


            <K

              n={

                result.ndvi

                  ? `${(
                      result.ndvi.loss_fraction *
                      100
                    ).toFixed(1)}%`

                  : "—"

              }

              t="Vegetation loss signal"

            />


            <K

              n={

                score[0]

                  ? `${(
                      score[0].score *
                      100
                    ).toFixed(0)}%`

                  : "—"

              }

              t="Top semantic score"

            />


            <K

              n={
                result.before
                  .datetime
                  ?.slice(
                    0,
                    10
                  )
              }

              t="Before acquisition"

            />


            <K

              n={
                result.after
                  .datetime
                  ?.slice(
                    0,
                    10
                  )
              }

              t="After acquisition"

            />

          </div>


          <div className="compare">

            <div>

              <label>
                BEFORE
              </label>

              <img

                src={
                  `${API}${result.before.preview}`
                }

                alt="Before satellite imagery"

              />

            </div>


            <div>

              <label>
                AFTER
              </label>

              <img

                src={
                  `${API}${result.after.preview}`
                }

                alt="After satellite imagery"

              />

            </div>


            <div>

              <label>
                CHANGE MASK
              </label>

              <img

                src={
                  `${API}${result.mask}`
                }

                alt="Change mask"

              />

            </div>

          </div>

        </>

      )}


      {/* ======================================================
          COMPARISON
         ====================================================== */}

      {tab === "comparison" && (

        <div className="slider-wrap">

          <div className="slider-stage">

            <img

              src={
                `${API}${result.after.preview}`
              }

              alt="After"

            />


            <div className="clip">

              <img

                src={
                  `${API}${result.before.preview}`
                }

                alt="Before"

              />

            </div>


            <input

              type="range"

              min="0"

              max="100"

              value={
                t
              }

              onChange={e =>
                setT(
                  Number(
                    e.target.value
                  )
                )
              }

            />


            <span className="before-label">
              BEFORE
            </span>


            <span className="after-label">
              AFTER
            </span>

          </div>


          <p>

            Drag the slider to inspect the
            real satellite acquisitions.

          </p>

        </div>

      )}


      {/* ======================================================
          SEMANTIC
         ====================================================== */}

      {tab === "semantic" && (

        <div className="semantic">

          {score.map(
            item => (

              <div

                className="sem"

                key={
                  item.label
                }

              >

                <div>

                  <b>
                    {item.label}
                  </b>

                  <span>

                    {
                      (
                        item.score *
                        100
                      ).toFixed(1)
                    }%

                  </span>

                </div>


                <i>

                  <u

                    style={{
                      width:
                        `${item.score * 100}%`
                    }}

                  />

                </i>

              </div>

            )
          )}

        </div>

      )}


      {/* ======================================================
          MAP
         ====================================================== */}

      {tab === "map" && (

        <>

          <Map

            lat={
              lat
            }

            lon={
              lon
            }

            changes={
              result.changes
            }

          />


          <div className="map-meta">

            Each rectangle is a candidate
            change region derived from the
            real before/after imagery.
            Coordinates are exported as
            GeoJSON for further GIS work.

          </div>

        </>

      )}


      {/* ======================================================
          DATA
         ====================================================== */}

      {tab === "data" && (

        <table>

          <thead>

            <tr>

              <th>
                ID
              </th>

              <th>
                Confidence
              </th>

              <th>
                Area px
              </th>

              <th>
                Latitude
              </th>

              <th>
                Longitude
              </th>

            </tr>

          </thead>


          <tbody>

            {result.changes.map(
              change => (

                <tr
                  key={
                    change.id
                  }
                >

                  <td>
                    #{change.id}
                  </td>

                  <td>

                    {
                      (
                        change.confidence *
                        100
                      ).toFixed(0)
                    }%

                  </td>

                  <td>

                    {
                      change.area_px
                        .toLocaleString()
                    }

                  </td>

                  <td>

                    {
                      change.lat
                        .toFixed(5)
                    }

                  </td>

                  <td>

                    {
                      change.lon
                        .toFixed(5)
                    }

                  </td>

                </tr>

              )
            )}

          </tbody>

        </table>

      )}


      {/* ======================================================
          SEASONAL WARNING
         ====================================================== */}

      {result.seasonal_similarity && (

        <div

          className={
            `disclaimer ${
              result.seasonal_similarity.warning
                ? "season-warning"
                : ""
            }`
          }

        >

          {result.seasonal_similarity.warning
            ? `Seasonal warning: ${result.seasonal_similarity.message}`
            : result.seasonal_similarity.message}

        </div>

      )}


      {/* ======================================================
          DISCLAIMER
         ====================================================== */}

      <div className="disclaimer">

        Important: medium-resolution Sentinel-2
        imagery can produce false positives from
        clouds, haze, seasonal vegetation,
        shadows, illumination and registration
        errors. These outputs are decision-support
        signals, not autonomous operational
        determinations.

      </div>

    </section>

  );
}


// ============================================================
// KPI
// ============================================================

function K({
  n,
  t
}) {

  return (

    <div className="kpi">

      <b>
        {n}
      </b>

      <span>
        {t}
      </span>

    </div>

  );
}


// ============================================================
// ROOT
// ============================================================

createRoot(
  document.getElementById("root")
).render(
  <App />
);