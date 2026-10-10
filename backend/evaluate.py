"""RQ1: SGP4 error vs TLE age. Usage: python evaluate.py 25544 [http://localhost:8000] > error.csv
Each older TLE is propagated to the epoch of every newer TLE and compared with that newer TLE's
own position at its epoch (a proxy for truth; swap in published ephemeris for stronger results)."""
import sys, math, httpx
from datetime import datetime
from sgp4.api import Satrec, jday

norad = sys.argv[1]
base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
rows = sorted(httpx.get(f"{base}/api/history/{norad}", timeout=30).json(), key=lambda r: r["epoch"])
sats = [(datetime.fromisoformat(r["epoch"]), Satrec.twoline2rv(r["line1"], r["line2"])) for r in rows]
print("age_hours,error_km")
for i, (t0, s0) in enumerate(sats):
    for t1, s1 in sats[i + 1:i + 40]:
        jd, fr = jday(t1.year, t1.month, t1.day, t1.hour, t1.minute, t1.second + t1.microsecond / 1e6)
        e0, p0, _ = s0.sgp4(jd, fr)
        e1, p1, _ = s1.sgp4(jd, fr)
        if e0 == 0 and e1 == 0:
            print(f"{(t1 - t0).total_seconds() / 3600:.2f},{math.dist(p0, p1):.3f}")
