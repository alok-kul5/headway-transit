"""Dagster entry point: `dagster dev -m transit_pipeline.definitions`."""


import os

import dagster as dg
from dagster_dbt import DbtCliResource

from . import config

# dbt reads these; set absolute paths so it works from any working directory.
os.environ.setdefault("TRANSIT_RAW_DIR", config.RAW_DIR.as_posix())
os.environ.setdefault("TRANSIT_WAREHOUSE", config.WAREHOUSE_PATH.as_posix())

from . import export  # noqa: E402
from .assets import ingest  # noqa: E402
from .assets.dbt import dbt_project, transit_dbt_models  # noqa: E402

MART_KEYS = [
    dg.AssetKey(["marts", name])
    for name in ("agg_hourly_mode", "agg_route_performance", "agg_weather_impact", "agg_snapshot_timeline")
]


@dg.asset(group_name="serve", deps=MART_KEYS, kinds={"json"},
          description="JSON files the static dashboard reads (site/data).")
def dashboard_data() -> dg.MaterializeResult:
    sizes = export.export()
    return dg.MaterializeResult(metadata={f"rows_{k}": v for k, v in sizes.items()})


everything = dg.define_asset_job(
    "collect_and_build",
    selection=dg.AssetSelection.all(),
    description="Fetch a real-time snapshot and weather, rebuild the dbt models, export the dashboard data.",
)

defs = dg.Definitions(
    assets=[ingest.gtfs_schedule, ingest.trip_updates, ingest.weather_hourly, transit_dbt_models, dashboard_data],
    asset_checks=[
        ingest.trip_updates_unique_snapshots,
        ingest.trip_updates_fresh,
        ingest.weather_no_gaps,
        ingest.gtfs_feed_current,
    ],
    jobs=[everything],
    schedules=[dg.ScheduleDefinition(job=everything, cron_schedule="*/15 * * * *", execution_timezone=config.AGENCY_TIMEZONE)],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)
