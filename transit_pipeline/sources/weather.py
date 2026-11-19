"""Hourly weather for Boston from Open-Meteo, merged into one parquet file."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from .. import config

HOURLY_VARS = ["temperature_2m", "precipitation", "rain", "snowfall", "wind_speed_10m", "weather_code"]


def fetch(past_days: int = 3) -> dict:
    params = {
        "latitude": config.WEATHER_LAT,
        "longitude": config.WEATHER_LON,
        "hourly": ",".join(HOURLY_VARS),
        "past_days": past_days,
        "forecast_days": 1,
        "timezone": "UTC",
        "timeformat": "unixtime",
    }
    r = requests.get(config.WEATHER_URL, params=params, timeout=config.HTTP_TIMEOUT,
                     headers={"User-Agent": config.USER_AGENT})
    r.raise_for_status()
    return r.json()


def parse(payload: dict, now: float | None = None) -> pd.DataFrame:
    """Hourly rows up to the current hour (forecast hours are dropped)."""
    hourly = payload["hourly"]
    df = pd.DataFrame({"hour_ts": hourly["time"], **{v: hourly[v] for v in HOURLY_VARS}})
    now = time.time() if now is None else now
    df = df[df["hour_ts"] <= now].copy()
    df["fetched_ts"] = int(now)
    return df


def merge(new: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Upsert by hour. Newer fetches win because recent hours get revised."""
    if path.exists():
        old = pd.read_parquet(path)
        new = pd.concat([old, new], ignore_index=True)
    merged = (
        new.sort_values(["hour_ts", "fetched_ts"])
        .drop_duplicates("hour_ts", keep="last")
        .reset_index(drop=True)
    )
    return merged
