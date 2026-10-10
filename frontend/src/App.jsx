import { useEffect, useMemo, useRef, useState } from "react";
import * as C from "cesium";
import { twoline2satrec, propagate, gstime, eciToGeodetic, eciToEcf, degreesLat, degreesLong } from "satellite.js";

const GROUPS = [["stations", "Stations"], ["starlink", "Starlink"], ["gps-ops", "GPS"], ["weather", "Weather"], ["science", "Science"], ["geo", "Geostationary"], ["active", "All active"]];
const BASE = C.Color.WHITE.withAlpha(0.8);
const HOT = C.Color.WHITE;
const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const when = (t) => new Date(t).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });

const kindOf = (name, group) => {
  if (/\bISS\b|ZARYA/.test(name)) return "iss";
  if (group === "starlink" || /STARLINK/.test(name)) return "starlink";
  if (group === "gps-ops" || /GPS|NAVSTAR/.test(name)) return "gps";
  if (group === "weather" || /NOAA|GOES|METOP|METEOSAT|FENGYUN|HIMAWARI/.test(name)) return "weather";
  if (group === "science" || /HST|HUBBLE|TERRA|AQUA|LANDSAT|SENTINEL/.test(name)) return "science";
  return "generic";
};

// ECEF position plus an orientation: up = away from Earth, nose along the direction of travel.
function poseAt(rec, date) {
  const f = (d) => { const p = propagate(rec, d).position; if (!p) return null; const e = eciToEcf(p, gstime(d)); return new C.Cartesian3(e.x * 1e3, e.y * 1e3, e.z * 1e3); };
  const p = f(date), n = f(new Date(date.getTime() + 1000));
  if (!p || !n) return null;
  const inv = C.Matrix4.inverseTransformation(C.Transforms.eastNorthUpToFixedFrame(p), new C.Matrix4());
  const dv = C.Matrix4.multiplyByPointAsVector(inv, C.Cartesian3.subtract(n, p, new C.Cartesian3()), new C.Cartesian3());
  return { pos: p, q: C.Transforms.headingPitchRollQuaternion(p, new C.HeadingPitchRoll(Math.atan2(-dv.y, dv.x), 0, 0)) };
}

function locate(rec, date) {
  const pv = propagate(rec, date);
  if (!pv.position || !pv.velocity) return null;
  const g = eciToGeodetic(pv.position, gstime(date)), v = pv.velocity;
  return { lat: degreesLat(g.latitude), lon: degreesLong(g.longitude), alt: g.height, speed: Math.hypot(v.x, v.y, v.z) };
}

export default function App() {
  const box = useRef(), viewer = useRef(), pts = useRef(), ring = useRef(), worker = useRef(), tip = useRef(), hov = useRef(null), ent = useRef(), pose = useRef(null), groupRef = useRef("stations");
  const sats = useRef([]), sel = useRef(null), selRec = useRef(null), busy = useRef(false), gen = useRef(0);
  const [group, setGroup] = useState("stations");
  const [list, setList] = useState([]);
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState(null);
  const [info, setInfo] = useState(null);
  const [state, setState] = useState("loading");
  const [tries, setTries] = useState(0);
  const [passes, setPasses] = useState([]);
  const [pstate, setPstate] = useState("idle");
  const [alerts, setAlerts] = useState([]);
  const [note, setNote] = useState("");
  const [fps, setFps] = useState(0);
  const [follow, setFollow] = useState(false);
  const [err, setErr] = useState("");

  const style = (i, on, size = 10) => {
    const pt = sats.current[i]?.pt;
    if (pt) { pt.pixelSize = on ? size : 3; pt.color = on ? HOT : BASE; }
  };

  function choose(i, fly) {
    const s = sats.current[i];
    if (!s) return;
    if (sel.current != null) style(sel.current, false);
    sel.current = i; style(i, true);
    selRec.current = twoline2satrec(s.line1, s.line2);
    setPicked(s.norad); setPasses([]); setPstate("idle"); setNote(""); setFollow(false);
    const v = viewer.current;
    v.trackedEntity = undefined;
    if (ent.current) v.entities.remove(ent.current);
    pose.current = poseAt(selRec.current, new Date());
    ent.current = v.entities.add({
      position: new C.CallbackPositionProperty(() => pose.current?.pos, false),
      orientation: new C.CallbackProperty(() => pose.current?.q, false),
      model: { uri: `/models/${kindOf(s.name, groupRef.current)}.glb`, minimumPixelSize: 72, maximumScale: 40000, runAnimations: true },
      label: { text: s.name, font: "600 13px Schibsted Grotesk, system-ui, sans-serif", fillColor: C.Color.WHITE, outlineColor: C.Color.BLACK, outlineWidth: 3,
        style: C.LabelStyle.FILL_AND_OUTLINE, verticalOrigin: C.VerticalOrigin.BOTTOM, pixelOffset: new C.Cartesian2(0, -46) },
    });
    const p = locate(selRec.current, new Date());
    setInfo(p);
    worker.current.postMessage({ type: "orbit", t: Date.now(), line1: s.line1, line2: s.line2 });
    if (fly && p) viewer.current.camera.flyTo({ destination: C.Cartesian3.fromDegrees(p.lon, p.lat, p.alt * 1000 + 5e6), duration: still() ? 0 : 1.5 });
  }

  function close() {
    style(sel.current, false); sel.current = selRec.current = null;
    viewer.current.trackedEntity = undefined; setFollow(false);
    if (ent.current) viewer.current.entities.remove(ent.current);
    ent.current = null; ring.current.removeAll(); setPicked(null);
  }

  function toggleFollow() {
    const on = !follow;
    viewer.current.trackedEntity = on ? ent.current : undefined;
    setFollow(on);
  }

  function predict() {
    const s = sats.current[sel.current];
    setPstate("busy");
    navigator.geolocation.getCurrentPosition(
      (g) => worker.current.postMessage({ type: "passes", t: Date.now(), line1: s.line1, line2: s.line2, lat: g.coords.latitude, lon: g.coords.longitude, alt: g.coords.altitude || 0 }),
      () => setPstate("denied"), { timeout: 10000 });
  }

  async function alertMe(p, name) {
    const ok = "Notification" in window && (await Notification.requestPermission()) === "granted";
    if (!ok) return setNote("Allow notifications in your browser to set alerts.");
    setTimeout(() => new Notification(`${name} rises in 5 minutes`, { body: `Peaks at ${p.max.toFixed(0)}° above the horizon` }), Math.max(p.start - Date.now() - 300000, 0));
    setAlerts((a) => [...a, p.start]);
    setNote("Alerts only fire while this tab stays open.");
  }

  useEffect(() => {
    const v = new C.Viewer(box.current, {
      baseLayer: C.ImageryLayer.fromProviderAsync(C.TileMapServiceImageryProvider.fromUrl(C.buildModuleUrl("Assets/Textures/NaturalEarthII"))),
      baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false, navigationHelpButton: false,
      animation: false, timeline: false, fullscreenButton: false, infoBox: false, selectionIndicator: false,
    });
    const g = v.scene.globe, sc = v.scene;
    g.enableLighting = true; g.showGroundAtmosphere = true; g.dynamicAtmosphereLighting = true; g.dynamicAtmosphereLightingFromSun = true;
    g.atmosphereLightIntensity = 12; g.maximumScreenSpaceError = 1.5;
    sc.skyAtmosphere.show = true; sc.highDynamicRange = true; sc.sun.show = true; sc.moon.show = true;
    const bl = sc.postProcessStages.bloom; bl.enabled = true; bl.uniforms.brightness = -0.35; bl.uniforms.contrast = 110; bl.uniforms.sigma = 3.5;
    v.clock.currentTime = C.JulianDate.now(); v.clock.shouldAnimate = true;
    // Real imagery on top of the bundled offline map (falls back to it if offline); NASA night lights on the dark side.
    const day = v.imageryLayers.addImageryProvider(new C.UrlTemplateImageryProvider({ url: "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", maximumLevel: 18, credit: "Esri, Maxar, Earthstar Geographics" }));
    day.nightAlpha = 0.12;
    const night = v.imageryLayers.addImageryProvider(new C.UrlTemplateImageryProvider({ url: "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/2016-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png", maximumLevel: 8, credit: "NASA GIBS / VIIRS" }));
    night.dayAlpha = 0; night.nightAlpha = 1;
    v.scene.backgroundColor = C.Color.fromCssColorString("#0a1626");
    pts.current = v.scene.primitives.add(new C.PointPrimitiveCollection());
    ring.current = v.scene.primitives.add(new C.PolylineCollection());
    // Orbit ring is stored in the inertial (TEME) frame and rotated with the Earth each frame.
    v.scene.preRender.addEventListener((_, t) => {
      const m = C.Transforms.computeTemeToPseudoFixedMatrix(t);
      if (m) ring.current.modelMatrix = C.Matrix4.fromRotationTranslation(m, C.Cartesian3.ZERO, ring.current.modelMatrix);
      if (selRec.current) pose.current = poseAt(selRec.current, C.JulianDate.toDate(t)) || pose.current;
    });
    const h = new C.ScreenSpaceEventHandler(v.scene.canvas);
    h.setInputAction((e) => { const p = v.scene.pick(e.position); if (p && typeof p.id === "number") choose(p.id, false); }, C.ScreenSpaceEventType.LEFT_CLICK);
    h.setInputAction((e) => {
      const p = v.scene.pick(e.endPosition), i = p && typeof p.id === "number" ? p.id : null, el = tip.current;
      if (hov.current != null && hov.current !== sel.current) style(hov.current, false);
      hov.current = i;
      v.scene.canvas.style.cursor = i != null ? "pointer" : "";
      if (i == null) return el.classList.remove("on");
      if (i !== sel.current) style(i, true, 8);
      el.textContent = sats.current[i].name;
      el.style.transform = `translate(${e.endPosition.x + 14}px, ${e.endPosition.y + 14}px)`;
      el.classList.add("on");
    }, C.ScreenSpaceEventType.MOUSE_MOVE);
    viewer.current = v;

    const w = new Worker(new URL("./propagation.worker.js", import.meta.url), { type: "module" });
    const P = new C.Cartesian3();
    w.onmessage = ({ data: m }) => {
      if (m.type === "pos") {
        busy.current = false;
        if (m.gen !== gen.current) return;
        sats.current.forEach((s, i) => {
          const x = m.buf[3 * i];
          if (x !== x) { s.pt.show = false; return; }
          P.x = x; P.y = m.buf[3 * i + 1]; P.z = m.buf[3 * i + 2];
          s.pt.position = P; s.pt.show = true;
        });
      } else if (m.type === "orbit") {
        ring.current.removeAll();
        const pos = [];
        for (let i = 0; i < m.buf.length; i += 3) pos.push(new C.Cartesian3(m.buf[i], m.buf[i + 1], m.buf[i + 2]));
        ring.current.add({ positions: pos, loop: true, width: 1.5, material: C.Material.fromType("Color", { color: HOT.withAlpha(0.8) }) });
      } else if (m.type === "passes") { setPasses(m.res); setPstate("ok"); }
    };
    worker.current = w;

    const id = setInterval(() => {
      if (!busy.current && sats.current.length) { busy.current = true; w.postMessage({ type: "tick", t: Date.now() }); }
      if (selRec.current) setInfo(locate(selRec.current, new Date()));
    }, 1000);
    let n = 0, last = performance.now(), raf;
    const loop = (t) => { n++; if (t - last >= 1000) { setFps(n); n = 0; last = t; } raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    return () => { clearInterval(id); cancelAnimationFrame(raf); h.destroy(); w.terminate(); v.destroy(); };
  }, []);

  useEffect(() => {
    let dead = false;
    groupRef.current = group;
    setState("loading"); setPicked(null); setInfo(null); setQ("");
    fetch(`/api/tle/${group}`)
      .then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`); return r.json(); })
      .then((d) => {
        if (dead) return;
        pts.current.removeAll(); ring.current.removeAll(); sel.current = selRec.current = null;
        viewer.current.trackedEntity = undefined; viewer.current.entities.removeAll(); ent.current = null; hov.current = null; setFollow(false);
        sats.current = d.map((s, i) => ({ ...s, pt: pts.current.add({ position: C.Cartesian3.ZERO, pixelSize: 3, color: BASE, id: i, show: false }) }));
        gen.current++; busy.current = false;
        worker.current.postMessage({ type: "init", gen: gen.current, tles: d });
        setList(d.map((s, i) => ({ i, name: s.name, norad: s.norad })));
        setState("ok");
      })
      .catch((e) => { if (!dead) { setErr(e.message); setState("error"); } });
    return () => { dead = true; };
  }, [group, tries]);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return list.filter((s) => !t || s.name.toLowerCase().includes(t) || String(s.norad).includes(t)).slice(0, 60);
  }, [list, q]);
  const cur = picked && sats.current.find((s) => s.norad === picked);

  return (
    <div className="app">
      <div ref={box} className="globe" />
      <div ref={tip} className="tip" />
      <aside className="panel">
        <header>
          <h1>Overhead</h1>
          <p className="status" role="status">
            {state === "loading" && "Loading orbits"}
            {state === "ok" && `${list.length.toLocaleString()} satellites live, ${fps} fps`}
            {state === "error" && `Tracking data unavailable: ${err}`}
          </p>
          {state === "error" && <button className="act" onClick={() => setTries(tries + 1)}>Try again</button>}
        </header>
        <div className="groups">
          {GROUPS.map(([id, label]) => (
            <button key={id} aria-pressed={group === id} className={group === id ? "on" : ""} onClick={() => setGroup(id)}>{label}</button>
          ))}
        </div>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name or NORAD ID" aria-label="Search satellites" />
        <ul className="list">
          {shown.map((s, n) => (
            <li key={s.i} style={{ "--n": Math.min(n, 14) }}><button className={s.norad === picked ? "on" : ""} onClick={() => choose(s.i, true)}><span>{s.name}</span><small>{s.norad}</small></button></li>
          ))}
          {state === "ok" && !shown.length && <li className="empty">No match. Try a NORAD ID or part of a name.</li>}
        </ul>
        {cur && (
          <section className="detail">
            <div className="row"><h2>{cur.name}</h2><button aria-label="Close details" onClick={close}>×</button></div>
            <dl>
              <div><dt>Altitude</dt><dd>{info ? `${info.alt.toFixed(0)} km` : "…"}</dd></div>
              <div><dt>Speed</dt><dd>{info ? `${info.speed.toFixed(2)} km/s` : "…"}</dd></div>
              <div><dt>Latitude</dt><dd>{info ? `${info.lat.toFixed(2)}°` : "…"}</dd></div>
              <div><dt>Longitude</dt><dd>{info ? `${info.lon.toFixed(2)}°` : "…"}</dd></div>
            </dl>
            <button className="act wide ghost" onClick={toggleFollow}>{follow ? "Exit close-up" : "Close-up 3D view"}</button>
            <button className="act wide" onClick={predict} disabled={pstate === "busy"}>{pstate === "busy" ? "Calculating passes" : "Predict passes at my location"}</button>
            {pstate === "denied" && <p className="note">Location is blocked. Allow location access in your browser to see passes.</p>}
            {pstate === "ok" && !passes.length && <p className="note">No passes above 10° in the next 24 hours.</p>}
            <ul className="passes">
              {passes.map((p) => (
                <li key={p.start}>
                  <span>{when(p.start)}<small>{p.max.toFixed(0)}° peak, {Math.max(1, Math.round((p.end - p.start) / 60000))} min</small></span>
                  <button disabled={alerts.includes(p.start)} onClick={() => alertMe(p, cur.name)}>{alerts.includes(p.start) ? "Alert set" : "Alert me"}</button>
                </li>
              ))}
            </ul>
            {note && <p className="note">{note}</p>}
          </section>
        )}
        <footer className="credits">Orbits: CelesTrak · Imagery: Esri, NASA GIBS · 3D: CesiumJS</footer>
      </aside>
    </div>
  );
}
