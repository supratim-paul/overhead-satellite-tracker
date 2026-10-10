import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone
from fastapi.testclient import TestClient
import main

ISS = """ISS (ZARYA)
1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9990
2 25544  51.6400 208.9163 0006317  69.9862  25.2906 15.49560532 99999
"""


def test_parse():
    d = main.parse(ISS)
    assert d == [{"name": "ISS (ZARYA)", "line1": ISS.splitlines()[1], "line2": ISS.splitlines()[2], "norad": 25544}]


def test_parse_rejects_garbage():
    try:
        main.parse("Invalid query\nnot a tle\nat all")
        assert False
    except ValueError:
        pass


def test_epoch():
    assert main.epoch(ISS.splitlines()[1]) == datetime(2024, 1, 1, 12, tzinfo=timezone.utc)


def test_api(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA", tmp_path)
    main.mem.clear()
    main.disk_write("stations", main.parse(ISS))
    with TestClient(main.app) as c:
        assert c.get("/api/health").json()["status"] == "ok"
        assert c.get("/api/tle/nope").status_code == 404
        assert c.get("/api/tle/stations").json()[0]["norad"] == 25544  # served from disk cache, no network
        assert c.get("/api/history/25544").json() == []


def test_seed_fallback(tmp_path, monkeypatch):
    seed = tmp_path / "seed"; seed.mkdir()
    (seed / "gps-ops.json").write_text('[{"name":"S","line1":"1 1U","line2":"2 1","norad":1}]')
    monkeypatch.setattr(main, "DATA", tmp_path / "data"); (tmp_path / "data").mkdir()
    monkeypatch.setattr(main, "SEED", seed)
    main.mem.clear(); main.fail_until["gps-ops"] = 9e12  # pretend CelesTrak is blocked
    with TestClient(main.app) as c:
        assert c.get("/api/tle/gps-ops").json()[0]["name"] == "S"
        assert c.get("/api/tle/weather").status_code == 502
