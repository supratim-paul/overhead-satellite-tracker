import os, time, json, sqlite3, asyncio, logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("overhead")
ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("DATA_DIR", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
SEED = ROOT / "seed"  # committed snapshot, last-resort fallback when CelesTrak is unreachable
fail_until: dict[str, float] = {}
SOURCE = "https://celestrak.org/NORAD/elements/gp.php"
GROUPS = {"stations", "starlink", "gps-ops", "weather", "science", "geo", "active"}
TTL = int(os.getenv("TLE_TTL", 7200))
mem: dict[str, tuple[float, list]] = {}
locks: dict[str, asyncio.Lock] = {g: asyncio.Lock() for g in GROUPS}
client: httpx.AsyncClient | None = None
db: sqlite3.Connection | None = None
db_lock = asyncio.Lock()
bg: set = set()  # background history writes, awaited before the DB is closed


def open_db():
    c = sqlite3.connect(DATA / "tle.db", check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS tle_history(
        norad INTEGER, name TEXT, epoch TEXT, line1 TEXT, line2 TEXT,
        fetched_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(norad, epoch))""")
    c.commit()
    return c


def parse(text):
    ln = [l.strip() for l in text.splitlines() if l.strip()]
    return [{"name": ln[i], "line1": ln[i + 1], "line2": ln[i + 2], "norad": int(ln[i + 1][2:7])}
            for i in range(0, len(ln) - 2, 3)]


def epoch(l1):
    yy = int(l1[18:20])
    return datetime(2000 + yy if yy < 57 else 1900 + yy, 1, 1, tzinfo=timezone.utc) + timedelta(days=float(l1[20:32]) - 1)


def _store(data):
    rows = [(d["norad"], d["name"], epoch(d["line1"]).isoformat(), d["line1"], d["line2"]) for d in data]
    db.executemany("INSERT OR IGNORE INTO tle_history(norad,name,epoch,line1,line2) VALUES(?,?,?,?,?)", rows)
    db.commit()


async def store(data):
    try:
        async with db_lock:
            await asyncio.to_thread(_store, data)
    except Exception:
        log.exception("history write failed")


def _history(norad):
    cur = db.execute("SELECT name,epoch,line1,line2 FROM tle_history WHERE norad=? ORDER BY epoch DESC LIMIT 200", (norad,))
    return [dict(zip(("name", "epoch", "line1", "line2"), r)) for r in cur.fetchall()]


def disk_read(group, max_age=None):
    f = DATA / f"{group}.json"
    if not f.exists() or (max_age is not None and time.time() - f.stat().st_mtime > max_age):
        return None
    return f.stat().st_mtime, json.loads(f.read_text())


def seed_read(group):
    f = SEED / f"{group}.json"
    return json.loads(f.read_text()) if f.exists() else None


def disk_write(group, data):
    (DATA / f"{group}.json").write_text(json.dumps(data))


@asynccontextmanager
async def lifespan(_):
    global client, db
    db = open_db()
    client = httpx.AsyncClient(timeout=60, follow_redirects=True, headers={"User-Agent": "overhead-tracker/2.0"})
    yield
    await asyncio.gather(*bg, return_exceptions=True)  # finish pending writes before closing the DB
    await client.aclose()
    db.close()


app = FastAPI(title="Overhead Satellite Tracker", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.get("/api/health")
def health():
    return {"status": "ok", "cached": sorted(mem), "history": db is not None}


@app.get("/api/tle/{group}")
async def tle(group: str):
    if group not in GROUPS:
        raise HTTPException(404, "Unknown group")
    hit = mem.get(group)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    async with locks[group]:  # one upstream fetch per group at a time
        hit = mem.get(group)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
        fresh = await asyncio.to_thread(disk_read, group, TTL)  # survives restarts, avoids CelesTrak rate limits
        if fresh:
            mem[group] = fresh
            return fresh[1]
        err, data = "CelesTrak recently unreachable, retrying later", None
        if time.time() >= fail_until.get(group, 0):
            for url, params in ((SOURCE, {"GROUP": group, "FORMAT": "tle"}), (f"https://celestrak.org/NORAD/elements/{group}.txt", None)):
                try:
                    r = await client.get(url, params=params, timeout=10)
                    r.raise_for_status()
                    data = parse(r.text)
                    if data:
                        break
                    err = "empty response"
                except httpx.HTTPStatusError as e:
                    err = f"CelesTrak returned {e.response.status_code}"
                except (httpx.HTTPError, ValueError, IndexError) as e:
                    err = f"{type(e).__name__}: {e}"[:120]
            if not data:
                fail_until[group] = time.time() + 300  # don't make every visitor wait on a blocked source
        if not data:
            stale = (hit and hit[1]) or ((await asyncio.to_thread(disk_read, group)) or (0, None))[1] or await asyncio.to_thread(seed_read, group)
            if stale:
                return stale  # stale beats nothing
            raise HTTPException(502, err)
        mem[group] = (time.time(), data)
        await asyncio.to_thread(disk_write, group, data)
        t = asyncio.create_task(store(data))
        bg.add(t)
        t.add_done_callback(bg.discard)
        return data


@app.get("/api/history/{norad}")
async def history(norad: int):
    async with db_lock:
        return await asyncio.to_thread(_history, norad)


for p in (ROOT.parent / "frontend" / "dist", ROOT / "static"):
    if (p / "index.html").exists():
        app.mount("/", StaticFiles(directory=p, html=True), name="web")
        break
