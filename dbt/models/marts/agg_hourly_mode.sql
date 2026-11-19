-- Delay by hour of day and mode.
select
    local_hour,
    mode,
    count(*)                                              as observations,
    round(median(delay_min), 2)                           as median_delay_min,
    round(quantile_cont(delay_min, 0.9), 2)               as p90_delay_min,
    round(100.0 * avg(is_on_time::int), 1)                as on_time_pct
from {{ ref('fct_delay_observations') }}
group by local_hour, mode
