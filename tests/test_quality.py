from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from transit_pipeline import quality

TZ = ZoneInfo("America/New_York")
NOON = int(datetime(2026, 11, 19, 12, 0, tzinfo=TZ).timestamp())
THREE_AM = int(datetime(2026, 11, 19, 3, 0, tzinfo=TZ).timestamp())


def batch(n=100, snapshot=NOON, matched=1.0, **overrides):
    df = pd.DataFrame({
        "snapshot_ts": snapshot,
        "trip_id": [f"t{i}" for i in range(n)],
        "route_id": "1",
        "trip_schedule_relationship": "SCHEDULED",
        "predicted_ts": snapshot + 120,
        "scheduled_ts": pd.array([snapshot if i < n * matched else None for i in range(n)], dtype="Int64"),
    })
    for k, v in overrides.items():
        df[k] = v
    df.attrs["snapshot_ts"] = snapshot
    return df


def test_good_batch_passes():
    assert quality.validate_trip_updates(batch(), fetched_ts=NOON + 30) == []


def test_stale_feed_is_rejected():
    problems = quality.validate_trip_updates(batch(), fetched_ts=NOON + 3600)
    assert any("stale" in p for p in problems)


def test_too_few_trips_in_daytime_is_rejected_but_fine_overnight():
    assert any("only 5 trips" in p for p in quality.validate_trip_updates(batch(5), NOON + 10))
    assert quality.validate_trip_updates(batch(5, snapshot=THREE_AM), THREE_AM + 10) == []


def test_duplicates_and_empty_ids_are_rejected():
    df = batch()
    df.loc[1, "trip_id"] = "t0"
    df.loc[2, "route_id"] = ""
    problems = quality.validate_trip_updates(df, NOON + 10)
    assert any("duplicate" in p for p in problems)
    assert any("empty route_id" in p for p in problems)


def test_far_future_predictions_are_rejected():
    df = batch()
    df.loc[0, "predicted_ts"] = NOON + 10 * 3600
    assert any("6h" in p for p in quality.validate_trip_updates(df, NOON + 10))


def test_low_schedule_match_rate_means_feeds_out_of_sync():
    problems = quality.validate_trip_updates(batch(matched=0.1), NOON + 10)
    assert any("out of sync" in p for p in problems)


def weather_df(**over):
    df = pd.DataFrame({"hour_ts": [0, 3600, 7200], "temperature_2m": [5.0, 6.0, 7.0], "precipitation": [0.0, 0.2, 0.0]})
    for k, v in over.items():
        df[k] = v
    return df


def test_weather_rules():
    assert quality.validate_weather(weather_df()) == []
    assert quality.validate_weather(weather_df(temperature_2m=[5.0, 99.0, 7.0]))
    assert quality.validate_weather(weather_df(precipitation=[0.0, -1.0, 0.0]))
    assert quality.validate_weather(weather_df(hour_ts=[0, 0, 3600]))
    assert quality.validate_weather(weather_df(hour_ts=[0, 1800, 3600]))


def test_gaps():
    assert quality.gaps(pd.Series([0, 3600, 7200])) == []
    assert quality.gaps(pd.Series([0, 3600, 5 * 3600]), max_gap_hours=3) == [(3600, 18000)]


def test_gtfs_counts():
    ok = {"routes": 100, "trips": 50_000, "stops": 8000, "stop_times": 1_000_000}
    assert quality.validate_gtfs_counts(ok) == []
    assert quality.validate_gtfs_counts({**ok, "stop_times": 10})
