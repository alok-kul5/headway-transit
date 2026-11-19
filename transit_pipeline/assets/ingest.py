"""Raw-layer assets: static schedule, real-time snapshots and weather."""


import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

import dagster as dg
import duckdb
import pandas as pd

from .. import config, quality
from ..sources import gtfs_rt, gtfs_static, weather


def _quarantine(kind: str, df: pd.DataFrame, problems: list[str]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = config.QUARANTINE_DIR / kind / stamp
    folder.mkdir(parents=True, exist_ok=True)
    df.to_parquet(folder / "batch.parquet", index=False)
    (folder / "problems.json").write_text(json.dumps(problems, indent=2))
    return folder


def _reject(context: dg.AssetExecutionContext, kind: str, df: pd.DataFrame, problems: list[str]):
    folder = _quarantine(kind, df, problems)
    for p in problems:
        context.log.error(f"{kind}: {p}")
    raise dg.Failure(
        description=f"{kind} batch failed validation and was quarantined; downstream assets will not run.",
        metadata={"problems": dg.MetadataValue.json(problems), "quarantine": str(folder)},
    )


GTFS_KEYS = {name: dg.AssetKey(["raw", f"gtfs_{name}"]) for name in ("routes", "stops", "stop_times")}


@dg.multi_asset(
    group_name="ingest",
    specs=[
        dg.AssetSpec(key, kinds={"python", "parquet"}, description=f"MBTA static GTFS {name}.txt as parquet.")
        for name, key in GTFS_KEYS.items()
    ],
    description="Latest MBTA static GTFS schedule. Only re-downloaded when the server reports a new version.",
)
def gtfs_schedule(context: dg.AssetExecutionContext):
    result = gtfs_static.refresh()
    problems = quality.validate_gtfs_counts(result.row_counts)
    if problems:
        raise dg.Failure(description="static GTFS failed validation", metadata={"problems": dg.MetadataValue.json(problems)})
    context.log.info("downloaded new schedule" if result.changed else "schedule unchanged, kept local copy")
    for name, key in GTFS_KEYS.items():
        yield dg.MaterializeResult(
            asset_key=key,
            metadata={"changed": result.changed, "last_modified": result.last_modified or "",
                      "rows": result.row_counts.get(name, 0)},
        )


@dg.asset(key_prefix="raw", group_name="ingest", deps=[GTFS_KEYS["stop_times"]], kinds={"python", "parquet"},
          description="One real-time TripUpdates snapshot: the next stop and predicted time for every active trip, "
                      "with the scheduled time attached.")
def trip_updates(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    fetched = time.time()
    df = gtfs_rt.parse(gtfs_rt.fetch())
    attrs = dict(df.attrs)
    df = gtfs_rt.attach_schedule(df)
    df.attrs.update(attrs)

    problems = quality.validate_trip_updates(df, fetched)
    if problems:
        _reject(context, "trip_updates", df, problems)

    snap = attrs["snapshot_ts"]
    day = datetime.fromtimestamp(snap, UTC).strftime("%Y-%m-%d")
    out = config.TRIP_UPDATES_DIR / f"date={day}" / f"snapshot_{snap}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    matched = float(df["scheduled_ts"].notna().mean()) if len(df) else 0.0
    return dg.MaterializeResult(
        metadata={
            "snapshot_ts": snap,
            "trips": len(df),
            "schedule_match_rate": round(matched, 3),
            "path": str(out),
        }
    )


@dg.asset(key_prefix="raw", group_name="ingest", kinds={"python", "parquet"},
          description="Hourly Boston weather from Open-Meteo, merged so recent hours are revised.")
def weather_hourly(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    new = weather.parse(weather.fetch())
    path = config.WEATHER_DIR / "weather.parquet"
    merged = weather.merge(new, path)
    problems = quality.validate_weather(merged)
    if problems:
        _reject(context, "weather", new, problems)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(path, index=False)
    return dg.MaterializeResult(metadata={"hours": len(merged), "latest_hour": int(merged["hour_ts"].max())})


# --- checks on the accumulated raw data -------------------------------------
# These look at everything stored so far (not just the latest batch). Blocking
# checks stop dbt from building on top of a broken raw layer.

def _snapshots() -> pd.DataFrame:
    files = (config.TRIP_UPDATES_DIR).as_posix()
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT snapshot_ts, count(*) AS trips FROM read_parquet('{files}/*/*.parquet') GROUP BY 1 ORDER BY 1"
        ).df()
    finally:
        con.close()


@dg.asset_check(asset=trip_updates, blocking=True, description="No snapshot file is stored twice.")
def trip_updates_unique_snapshots() -> dg.AssetCheckResult:
    files = list(config.TRIP_UPDATES_DIR.glob("*/*.parquet"))
    snaps = [f.stem for f in files]
    dupes = len(snaps) - len(set(snaps))
    return dg.AssetCheckResult(passed=bool(dupes == 0), metadata={"files": len(files), "duplicates": dupes})


@dg.asset_check(asset=trip_updates, description="A snapshot arrived in the last 2 hours (warns if collection has stalled).")
def trip_updates_fresh() -> dg.AssetCheckResult:
    snaps = _snapshots()
    age_h = (time.time() - snaps["snapshot_ts"].max()) / 3600 if len(snaps) else float("inf")
    return dg.AssetCheckResult(
        passed=bool(age_h < 2),
        severity=dg.AssetCheckSeverity.WARN,
        metadata={"snapshots": len(snaps), "latest_age_hours": round(float(age_h), 2)},
    )


@dg.asset_check(asset=weather_hourly, blocking=True, description="Hourly weather has no gaps longer than 3 hours.")
def weather_no_gaps() -> dg.AssetCheckResult:
    df = pd.read_parquet(config.WEATHER_DIR / "weather.parquet")
    found = quality.gaps(df["hour_ts"], max_gap_hours=3)
    return dg.AssetCheckResult(passed=bool(not found), metadata={"gaps": dg.MetadataValue.json(found[:20])})


@dg.asset_check(asset=GTFS_KEYS["stop_times"], blocking=True, description="The static schedule is still in its valid date range.")
def gtfs_feed_current() -> dg.AssetCheckResult:
    info = pd.read_parquet(config.GTFS_DIR / "feed_info.parquet")
    end = str(info["feed_end_date"].iloc[0]) if "feed_end_date" in info and len(info) else ""
    today = date.today().strftime("%Y%m%d")
    passed = not end or end >= today
    return dg.AssetCheckResult(passed=bool(passed), metadata={"feed_end_date": end, "today": today})
