"""Data quality rules for incoming batches.

Each `validate_*` function returns a list of problems (empty = good). The
ingest assets run these *before* writing anything: a batch with problems is
moved to `data/quarantine/` and the run stops, so bad data never reaches the
raw layer, dbt or the dashboard.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from . import config

# Overnight the MBTA runs almost nothing, so an empty-ish feed is normal then.
QUIET_HOURS = range(1, 5)
MIN_TRIPS_DAYTIME = 50
MAX_FEED_AGE_S = 15 * 60
MAX_PREDICTION_HORIZON_S = 6 * 3600
MIN_SCHEDULE_MATCH_RATE = 0.30


def validate_trip_updates(df: pd.DataFrame, fetched_ts: float) -> list[str]:
    problems: list[str] = []
    snapshot_ts = df.attrs.get("snapshot_ts")
    if not snapshot_ts:
        return ["feed header has no timestamp"]

    age = fetched_ts - snapshot_ts
    if age > MAX_FEED_AGE_S:
        problems.append(f"feed is stale: header is {age / 60:.0f} min old")
    if age < -300:
        problems.append(f"feed timestamp is {-age:.0f}s in the future")

    local_hour = datetime.fromtimestamp(snapshot_ts, ZoneInfo(config.AGENCY_TIMEZONE)).hour
    if local_hour not in QUIET_HOURS and len(df) < MIN_TRIPS_DAYTIME:
        problems.append(f"only {len(df)} trips in a daytime snapshot (expected >= {MIN_TRIPS_DAYTIME})")
    if df.empty:
        return problems

    for col in ("trip_id", "route_id", "predicted_ts"):
        n = int(df[col].isna().sum() + (df[col].astype(str) == "").sum())
        if n:
            problems.append(f"{n} rows with empty {col}")

    dupes = int(df.duplicated(["snapshot_ts", "trip_id"]).sum())
    if dupes:
        problems.append(f"{dupes} duplicate trips in one snapshot")

    horizon = (df["predicted_ts"] - snapshot_ts).abs()
    far = int((horizon > MAX_PREDICTION_HORIZON_S).sum())
    if far:
        problems.append(f"{far} predictions more than 6h from the snapshot time")

    if "scheduled_ts" in df:
        scheduled = df[df["trip_schedule_relationship"] == "SCHEDULED"]
        if len(scheduled) >= MIN_TRIPS_DAYTIME:
            rate = scheduled["scheduled_ts"].notna().mean()
            if rate < MIN_SCHEDULE_MATCH_RATE:
                problems.append(
                    f"only {rate:.0%} of scheduled trips matched the static GTFS "
                    "(static and real-time feeds are probably out of sync)"
                )
    return problems


def validate_weather(df: pd.DataFrame) -> list[str]:
    problems: list[str] = []
    if df.empty:
        return ["no weather rows"]
    if df["hour_ts"].duplicated().any():
        problems.append("duplicate weather hours")
    if (df["hour_ts"] % 3600 != 0).any():
        problems.append("weather timestamps are not on the hour")
    recent = df.sort_values("hour_ts").tail(24)
    nulls = int(recent[["temperature_2m", "precipitation"]].isna().sum().sum())
    if nulls:
        problems.append(f"{nulls} missing temperature/precipitation values in the last 24h")
    t = df["temperature_2m"].dropna()
    if ((t < -40) | (t > 45)).any():
        problems.append("temperature outside [-40, 45] °C")
    if (df["precipitation"].dropna() < 0).any():
        problems.append("negative precipitation")
    return problems


def validate_gtfs_counts(counts: dict[str, int]) -> list[str]:
    minimum = {"routes": 20, "trips": 1000, "stops": 500, "stop_times": 50_000}
    return [
        f"{name} has {counts.get(name, 0)} rows (expected >= {low})"
        for name, low in minimum.items()
        if counts.get(name, 0) < low
    ]


def gaps(hours: pd.Series, max_gap_hours: int = 1) -> list[tuple[int, int]]:
    """(start, end) pairs where consecutive hourly timestamps jump by more than allowed."""
    s = hours.sort_values().reset_index(drop=True)
    diff = s.diff()
    idx = diff[diff > max_gap_hours * 3600].index
    return [(int(s[i - 1]), int(s[i])) for i in idx]
