"""Export the marts as small JSON files for the static dashboard."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import duckdb

from . import config

SITE_DATA_DIR = config.SITE_DATA_DIR

QUERIES = {
    "summary": """
        select
            count(*)                                        as observations,
            count(distinct snapshot_ts)                     as snapshots,
            count(distinct route_id)                        as routes,
            count(distinct local_date)                      as days,
            min(snapshot_ts)                                as first_snapshot_ts,
            max(snapshot_ts)                                as last_snapshot_ts,
            round(median(delay_min), 2)                     as median_delay_min,
            round(quantile_cont(delay_min, 0.9), 2)         as p90_delay_min,
            round(100.0 * avg(is_on_time::int), 1)          as on_time_pct,
            round(100.0 * avg(is_late::int), 1)             as late_pct
        from marts.fct_delay_observations
    """,
    "by_mode": """
        select mode, count(*) as observations,
               round(median(delay_min), 2) as median_delay_min,
               round(quantile_cont(delay_min, 0.9), 2) as p90_delay_min,
               round(100.0 * avg(is_on_time::int), 1) as on_time_pct
        from marts.fct_delay_observations group by mode order by observations desc
    """,
    "hourly": "select * from marts.agg_hourly_mode order by mode, local_hour",
    "routes": """
        select * from marts.agg_route_performance
        where observations >= 30 order by median_delay_min desc
    """,
    "weather": "select * from marts.agg_weather_impact order by dimension, bucket, mode",
    "timeline": "select * exclude (snapshot_local) from marts.agg_snapshot_timeline order by snapshot_ts",
    "delay_histogram": """
        select greatest(-5, least(20, floor(delay_min)))::int as minute, count(*) as observations
        from marts.fct_delay_observations group by 1 order by 1
    """,
}


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def export(warehouse: Path = config.WAREHOUSE_PATH, out_dir: Path = SITE_DATA_DIR) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(warehouse), read_only=True)
    sizes = {}
    try:
        for name, sql in QUERIES.items():
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = [{c: _clean(v) for c, v in zip(cols, row, strict=True)} for row in cur.fetchall()]
            payload = rows[0] if name == "summary" else rows
            (out_dir / f"{name}.json").write_text(json.dumps(payload, default=str, separators=(",", ":")))
            sizes[name] = len(rows)
    finally:
        con.close()
    (out_dir / "meta.json").write_text(json.dumps({"generated_ts": int(time.time())}))
    return sizes
