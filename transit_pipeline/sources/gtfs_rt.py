"""Fetch a GTFS-realtime TripUpdates snapshot and flatten it.

For each trip we keep only the *next* stop it will reach: the prediction for an
imminent stop is the closest thing the feed has to the vehicle's actual delay.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
import requests
from google.transit import gtfs_realtime_pb2

from .. import config

COLUMNS = [
    "snapshot_ts", "trip_id", "route_id", "direction_id", "start_date", "start_time",
    "trip_schedule_relationship", "vehicle_id", "stop_id", "stop_sequence",
    "predicted_ts", "feed_delay_s", "scheduled_ts",
]


def fetch(url: str = config.GTFS_RT_TRIP_UPDATES_URL) -> bytes:
    r = requests.get(url, timeout=config.HTTP_TIMEOUT, headers={"User-Agent": config.USER_AGENT})
    r.raise_for_status()
    return r.content


def parse(pb: bytes) -> pd.DataFrame:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(pb)
    snapshot_ts = int(feed.header.timestamp)
    rows = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip = tu.trip
        for stu in tu.stop_time_update:
            # SKIPPED (1) and NO_DATA (2) stops carry no usable prediction.
            if stu.schedule_relationship in (1, 2):
                continue
            event = stu.arrival if stu.HasField("arrival") and stu.arrival.time else stu.departure
            if not event.time:
                continue
            rows.append({
                "snapshot_ts": snapshot_ts,
                "trip_id": trip.trip_id,
                "route_id": trip.route_id,
                "direction_id": int(trip.direction_id) if trip.HasField("direction_id") else None,
                "start_date": trip.start_date or None,
                "start_time": trip.start_time or None,
                "trip_schedule_relationship": gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.Name(
                    trip.schedule_relationship
                ),
                "vehicle_id": tu.vehicle.id or None,
                "stop_id": stu.stop_id or None,
                "stop_sequence": int(stu.stop_sequence) if stu.HasField("stop_sequence") else None,
                "predicted_ts": int(event.time),
                "feed_delay_s": int(event.delay) if event.HasField("delay") else None,
            })
            break  # first usable update = next stop
    df = pd.DataFrame(rows, columns=COLUMNS[:-1])
    df.attrs["snapshot_ts"] = snapshot_ts
    df.attrs["entities"] = len(feed.entity)
    return df


@lru_cache(maxsize=64)
def _service_day_origin(start_date: str, tz: str) -> int:
    """GTFS times count from 'noon minus 12h' on the service day (handles DST days)."""
    d = datetime.strptime(start_date, "%Y%m%d")
    noon = datetime(d.year, d.month, d.day, 12, tzinfo=ZoneInfo(tz))
    # Subtract on the absolute timeline: aware-datetime arithmetic in Python is
    # wall-clock arithmetic, which is an hour off on DST change days.
    return int(noon.timestamp()) - 12 * 3600


def gtfs_time_to_seconds(t: str) -> int:
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def scheduled_epoch(start_date: str, gtfs_time: str, tz: str = config.AGENCY_TIMEZONE) -> int:
    return _service_day_origin(start_date, tz) + gtfs_time_to_seconds(gtfs_time)


def attach_schedule(df: pd.DataFrame, gtfs_dir: Path = config.GTFS_DIR) -> pd.DataFrame:
    """Add the scheduled time for each (trip, stop_sequence).

    This is captured at fetch time on purpose: GTFS trip IDs change whenever
    the agency publishes a new schedule, so matching later could fail.
    """
    df = df.copy()
    if df.empty:
        df["scheduled_ts"] = pd.Series(dtype="Int64")
        return df
    stop_times = (gtfs_dir / "stop_times.parquet").as_posix()
    con = duckdb.connect()
    try:
        con.register("rt", df[["trip_id", "stop_sequence", "stop_id"]])
        sched = con.execute(
            f"""
            SELECT rt.trip_id, rt.stop_sequence,
                   coalesce(nullif(st.arrival_time, ''), st.departure_time) AS sched_time
            FROM rt
            JOIN read_parquet('{stop_times}') st
              ON st.trip_id = rt.trip_id
             AND (TRY_CAST(st.stop_sequence AS INTEGER) = rt.stop_sequence
                  OR (rt.stop_sequence IS NULL AND st.stop_id = rt.stop_id))
            """
        ).df()
    finally:
        con.close()
    df = df.merge(sched.drop_duplicates(["trip_id", "stop_sequence"]), on=["trip_id", "stop_sequence"], how="left")
    ok = df["sched_time"].notna() & df["start_date"].notna()
    df["scheduled_ts"] = pd.array([None] * len(df), dtype="Int64")
    df.loc[ok, "scheduled_ts"] = [
        scheduled_epoch(d, t) for d, t in zip(df.loc[ok, "start_date"], df.loc[ok, "sched_time"], strict=True)
    ]
    return df.drop(columns="sched_time")[COLUMNS]
