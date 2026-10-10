"""Download current TLEs into backend/seed so a deployed app always has data. Run from your own computer, then commit and push."""
import json, sys, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import main

(ROOT / "backend" / "seed").mkdir(exist_ok=True)
for g in sorted(main.GROUPS):
    url = f"{main.SOURCE}?GROUP={g}&FORMAT=tle"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "overhead-snapshot/1.0"})
        data = main.parse(urllib.request.urlopen(req, timeout=60).read().decode())
        (ROOT / "backend" / "seed" / f"{g}.json").write_text(json.dumps(data))
        print(f"{g}: {len(data)} satellites")
    except Exception as e:
        print(f"{g}: FAILED ({e})")
    time.sleep(3)  # be polite to CelesTrak
