"""Paths, feed URLs and constants. Everything can be overridden with env vars."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("TRANSIT_DATA_DIR", PROJECT_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
GTFS_DIR = RAW_DIR / "gtfs"                    # latest static schedule, as parquet
TRIP_UPDATES_DIR = RAW_DIR / "trip_updates"    # one parquet file per real-time snapshot
WEATHER_DIR = RAW_DIR / "weather"              # hourly weather, merged into one file
QUARANTINE_DIR = DATA_DIR / "quarantine"       # batches that failed validation
WAREHOUSE_PATH = Path(os.getenv("TRANSIT_WAREHOUSE", DATA_DIR / "warehouse.duckdb"))

DBT_PROJECT_DIR = PROJECT_ROOT / "dbt"
SITE_DATA_DIR = Path(os.getenv("TRANSIT_SITE_DATA", PROJECT_ROOT / "site" / "data"))

# MBTA (Boston) publishes both feeds openly, with no API key.
GTFS_STATIC_URL = os.getenv("GTFS_STATIC_URL", "https://cdn.mbta.com/MBTA_GTFS.zip")
GTFS_RT_TRIP_UPDATES_URL = os.getenv("GTFS_RT_URL", "https://cdn.mbta.com/realtime/TripUpdates.pb")
AGENCY_TIMEZONE = "America/New_York"

# Open-Meteo, also keyless. Coordinates: downtown Boston.
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_LAT, WEATHER_LON = 42.3601, -71.0589

GTFS_FILES = ("routes", "trips", "stops", "stop_times", "feed_info")

HTTP_TIMEOUT = 60
USER_AGENT = "transit-data-pipeline (portfolio project)"
