"""End-to-end tests of the Dagster job on synthetic data (no network).

The HTTP fetches are replaced with fixtures; everything else, including dbt
and the asset checks, runs for real against a temporary data directory.
"""

import importlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSIT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TRANSIT_WAREHOUSE", (tmp_path / "data" / "warehouse.duckdb").as_posix())
    monkeypatch.setenv("TRANSIT_RAW_DIR", (tmp_path / "data" / "raw").as_posix())
    monkeypatch.setenv("TRANSIT_SITE_DATA", str(tmp_path / "site"))
    monkeypatch.setenv("DAGSTER_HOME", str(tmp_path / "dagster"))
    # dagster-dbt shells out to `dbt`, which lives next to this Python.
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    (tmp_path / "dagster").mkdir()
    # dagster-dbt needs a manifest; build it first.
    subprocess.run(["dbt", "parse", "-q"], cwd=ROOT / "dbt", check=True, shell=os.name == "nt")
    import transit_pipeline.config as config
    importlib.reload(config)
    mods = {}
    for name in ["transit_pipeline.quality", "transit_pipeline.sources.gtfs_static", "transit_pipeline.sources.gtfs_rt",
                 "transit_pipeline.sources.weather", "transit_pipeline.export", "transit_pipeline.assets.ingest",
                 "transit_pipeline.assets.dbt", "transit_pipeline.definitions"]:
        mods[name] = importlib.reload(importlib.import_module(name))
    return tmp_path, mods


def fake_sources(monkeypatch, mods, now, bad=False):
    from tests.test_sources import make_feed

    gtfs_static = mods["transit_pipeline.sources.gtfs_static"]
    gtfs_rt = mods["transit_pipeline.sources.gtfs_rt"]
    weather = mods["transit_pipeline.sources.weather"]
    config = sys.modules["transit_pipeline.config"]

    def refresh():
        d = config.GTFS_DIR
        d.mkdir(parents=True, exist_ok=True)
        n = 60
        pd.DataFrame({"route_id": [f"r{i}" for i in range(30)], "route_short_name": [str(i) for i in range(30)],
                      "route_long_name": "Route", "route_type": "3", "route_color": "FFC72C"}).to_parquet(d / "routes.parquet")
        pd.DataFrame({"stop_id": [f"s{i}" for i in range(600)], "stop_name": "Stop", "stop_lat": "42.3",
                      "stop_lon": "-71.0"}).to_parquet(d / "stops.parquet")
        pd.DataFrame({"trip_id": [f"t{i}" for i in range(1500)], "route_id": "r1"}).to_parquet(d / "trips.parquet")
        pd.DataFrame({"trip_id": [f"t{i % n}" for i in range(60_000)], "stop_sequence": [str(i // n) for i in range(60_000)],
                      "stop_id": [f"s{(i // n) % 600}" for i in range(60_000)],
                      "arrival_time": sched_time, "departure_time": sched_time}).to_parquet(d / "stop_times.parquet")
        pd.DataFrame({"feed_end_date": ["20991231"]}).to_parquet(d / "feed_info.parquet")
        counts = {"routes": 30, "trips": 1500, "stops": 600, "stop_times": 60_000}
        return gtfs_static.StaticLoadResult(True, "x", counts)

    # Schedule every trip for "now" in Boston, and predict it 2 minutes late.
    local = datetime.fromtimestamp(now, ZoneInfo(config.AGENCY_TIMEZONE))
    service_date, sched_time = local.strftime("%Y%m%d"), local.strftime("%H:%M:%S")
    trips = [{"trip_id": f"t{i}", "route_id": f"r{i % 30}", "start_date": service_date,
              "stops": [(1, int(now) + 120, False)]} for i in range(60)]
    feed_ts = now - (7200 if bad else 0)  # bad = two-hour-old feed
    monkeypatch.setattr(gtfs_static, "refresh", refresh)
    monkeypatch.setattr(gtfs_rt, "fetch", lambda: make_feed(int(feed_ts), trips))
    hours = [int(now // 3600 * 3600 - 3600 * k) for k in range(30, -1, -1)]
    hourly = {"time": hours, **{v: [1.0] * len(hours) for v in weather.HOURLY_VARS}}
    monkeypatch.setattr(weather, "fetch", lambda: {"hourly": hourly})


def run_job(mods):
    defs = mods["transit_pipeline.definitions"].defs
    job = defs.resolve_job_def("collect_and_build")
    return job.execute_in_process(raise_on_error=False)


@pytest.mark.slow
def test_full_job_builds_marts_and_dashboard_json(env, monkeypatch):
    tmp, mods = env
    now = time.time()
    fake_sources(monkeypatch, mods, now)
    # Make every snapshot look like daytime so the min-trips rule applies normally.
    monkeypatch.setattr(mods["transit_pipeline.quality"], "QUIET_HOURS", range(0))
    result = run_job(mods)
    assert result.success, [e.message for e in result.all_events if e.is_failure]

    summary = json.loads((tmp / "site" / "summary.json").read_text())
    assert summary["observations"] == 60
    assert summary["snapshots"] == 1
    assert summary["median_delay_min"] == 2.0


@pytest.mark.slow
def test_bad_snapshot_is_quarantined_and_stops_downstream(env, monkeypatch):
    tmp, mods = env
    fake_sources(monkeypatch, mods, time.time(), bad=True)
    result = run_job(mods)
    assert not result.success

    failed = {e.step_key for e in result.all_events if e.event_type_value == "STEP_FAILURE"}
    assert "raw__trip_updates" in failed
    skipped_or_not_run = {e.step_key for e in result.all_events if e.event_type_value == "STEP_SUCCESS"}
    assert "transit_dbt_models" not in skipped_or_not_run
    assert "dashboard_data" not in skipped_or_not_run

    config = sys.modules["transit_pipeline.config"]
    quarantined = list((config.QUARANTINE_DIR / "trip_updates").glob("*/problems.json"))
    assert quarantined and "stale" in quarantined[0].read_text()
    assert not list(config.TRIP_UPDATES_DIR.glob("*/*.parquet"))
