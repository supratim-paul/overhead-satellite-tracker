import { twoline2satrec, propagate, gstime, eciToEcf, ecfToLookAngles } from "satellite.js";
let recs = [], gen = 0;
const D = Math.PI / 180;
onmessage = ({ data: m }) => {
  if (m.type === "init") {
    gen = m.gen;
    recs = m.tles.map((t) => twoline2satrec(t.line1, t.line2));
  } else if (m.type === "tick") {
    const d = new Date(m.t), g = gstime(d), out = new Float64Array(recs.length * 3);
    recs.forEach((r, i) => {
      const p = propagate(r, d).position;
      if (!p) { out[3 * i] = NaN; return; }
      const e = eciToEcf(p, g);
      out[3 * i] = e.x * 1000; out[3 * i + 1] = e.y * 1000; out[3 * i + 2] = e.z * 1000;
    });
    postMessage({ type: "pos", gen, buf: out }, [out.buffer]);
  } else if (m.type === "orbit") {
    const r = twoline2satrec(m.line1, m.line2), per = (2 * Math.PI) / r.no, out = [];
    for (let k = 0; k < 120; k++) {
      const p = propagate(r, new Date(m.t + ((k * per) / 120) * 60000)).position;
      if (p) out.push(p.x * 1000, p.y * 1000, p.z * 1000);
    }
    postMessage({ type: "orbit", buf: out });
  } else if (m.type === "passes") {
    const r = twoline2satrec(m.line1, m.line2), res = [];
    const obs = { latitude: m.lat * D, longitude: m.lon * D, height: m.alt / 1000 };
    let cur = null;
    for (let t = m.t; t < m.t + 864e5; t += 20000) {
      const d = new Date(t), p = propagate(r, d).position;
      if (!p) continue;
      const el = ecfToLookAngles(obs, eciToEcf(p, gstime(d))).elevation / D;
      if (el >= 10) {
        if (!cur) cur = { start: t, max: el };
        if (el > cur.max) cur.max = el;
        cur.end = t;
      } else if (cur) { res.push(cur); cur = null; }
    }
    if (cur) res.push(cur);
    postMessage({ type: "passes", res });
  }
};
