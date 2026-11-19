import io
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from google.transit import gtfs_realtime_pb2

from transit_pipeline.sources import gtfs_rt, gtfs_static, weather

TZ = ZoneInfo("America/New_York")


def make_feed(header_ts: int, trips: list[dict]) -> bytes:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = header_ts
    for i, t in enumerate(trips):
        e = feed.entity.add()
        e.id = str(i)
        tu = e.trip_update
        tu.trip.trip_id = t["trip_id"]
        tu.trip.route_id = t.get("route_id", "1")
        tu.trip.start_date = t.get("start_date", "20261119")
        tu.trip.direction_id = 0
        if t.get("added"):
            tu.trip.schedule_relationship = gtfs_realtime_pb2.TripDescriptor.ADDED
        tu.vehicle.id = f"v{i}"
        for seq, ts, skipped in t["stops"]:
            stu = tu.stop_time_update.add()
            stu.stop_sequence = seq
            stu.stop_id = f"s{seq}"
            if skipped:
                stu.schedule_relationship = gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SKIPPED
            else:
                stu.arrival.time = ts
    return feed.SerializeToString()


def test_parse_keeps_only_the_next_usable_stop():
    pb = make_feed(1000, [
        {"trip_id": "A", "stops": [(3, 1100, False), (4, 1200, False)]},
        {"trip_id": "B", "stops": [(1, 1050, True), (2, 1150, False)]},  # first stop skipped
        {"trip_id": "C", "added": True, "stops": [(7, 1300, False)]},
    ])
    df = gtfs_rt.parse(pb)
    assert df.attrs["snapshot_ts"] == 1000
    assert df.set_index("trip_id")["stop_sequence"].to_dict() == {"A": 3, "B": 2, "C": 7}
    assert df.set_index("trip_id").loc["C", "trip_schedule_relationship"] == "ADDED"


def test_parse_empty_feed():
    df = gtfs_rt.parse(make_feed(1000, []))
    assert df.empty and df.attrs["snapshot_ts"] == 1000


def test_scheduled_epoch_handles_times_past_midnight():
    # 25:30 on the 19th is 01:30 on the 20th.
    got = gtfs_rt.scheduled_epoch("20261119", "25:30:00")
    assert datetime.fromtimestamp(got, TZ) == datetime(2026, 11, 20, 1, 30, tzinfo=TZ)


@pytest.mark.parametrize("day", ["20261101", "20260308"])  # fall back / spring forward
def test_scheduled_epoch_on_dst_change_days(day):
    # GTFS counts from noon-minus-12h, so a daytime time like 08:00:00 is
    # still 08:00 on the wall clock even on the days the clocks change.
    got = gtfs_rt.scheduled_epoch(day, "08:00:00")
    assert datetime.fromtimestamp(got, TZ).strftime("%H:%M") == "08:00"


def test_attach_schedule_matches_trip_and_sequence(tmp_path):
    pd.DataFrame({
        "trip_id": ["A", "A"], "stop_sequence": ["3", "4"], "stop_id": ["s3", "s4"],
        "arrival_time": ["08:00:00", "08:05:00"], "departure_time": ["08:00:00", "08:05:00"],
    }).to_parquet(tmp_path / "stop_times.parquet")
    df = gtfs_rt.parse(make_feed(1000, [
        {"trip_id": "A", "stops": [(3, 1100, False)]},
        {"trip_id": "Z", "stops": [(1, 1100, False)]},  # not in the schedule
    ]))
    attached = gtfs_rt.attach_schedule(df, tmp_path)
    assert list(attached.columns) == gtfs_rt.COLUMNS
    out = attached.set_index("trip_id")
    assert out.loc["A", "scheduled_ts"] == gtfs_rt.scheduled_epoch("20261119", "08:00:00")
    assert pd.isna(out.loc["Z", "scheduled_ts"])


def test_gtfs_zip_to_parquet_handles_quoted_commas(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("routes.txt", 'route_id,route_long_name\n1,"Burlington via Medford, Woburn"\n')
        zf.writestr("stops.txt", "stop_id,stop_name\n001,Main St\n")
    counts = gtfs_static.zip_to_parquet(buf.getvalue(), tmp_path, files=("routes", "stops"))
    assert counts == {"routes": 1, "stops": 1}
    stops = pd.read_parquet(tmp_path / "stops.parquet")
    assert stops.loc[0, "stop_id"] == "001"  # leading zero kept
    assert pd.read_parquet(tmp_path / "routes.parquet").loc[0, "route_long_name"] == "Burlington via Medford, Woburn"


def test_gtfs_zip_missing_file_is_an_error(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("routes.txt", "route_id\n1\n")
    with pytest.raises(ValueError, match="missing"):
        gtfs_static.zip_to_parquet(buf.getvalue(), tmp_path, files=("routes", "stops"))


def test_weather_drops_future_hours_and_merge_prefers_latest(tmp_path):
    payload = {"hourly": {"time": [0, 3600, 7200], **{v: [1.0, 2.0, 3.0] for v in weather.HOURLY_VARS}}}
    first = weather.parse(payload, now=3600)
    assert list(first["hour_ts"]) == [0, 3600]

    path = tmp_path / "w.parquet"
    weather.merge(first, path).to_parquet(path)
    revised = weather.parse({"hourly": {"time": [3600], **{v: [9.0] for v in weather.HOURLY_VARS}}}, now=4000)
    merged = weather.merge(revised, path)
    assert merged.set_index("hour_ts").loc[3600, "temperature_2m"] == 9.0
    assert len(merged) == 2
