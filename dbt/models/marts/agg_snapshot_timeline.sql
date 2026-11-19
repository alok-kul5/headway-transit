-- System-wide health per snapshot, for the dashboard timeline.
select
    snapshot_ts,
    any_value(snapshot_local)                             as snapshot_local,
    count(*)                                              as vehicles,
    round(median(delay_min), 2)                           as median_delay_min,
    round(100.0 * avg(is_on_time::int), 1)                as on_time_pct,
    any_value(temperature_c)                              as temperature_c,
    any_value(precipitation_mm)                           as precipitation_mm
from {{ ref('fct_delay_observations') }}
group by snapshot_ts
