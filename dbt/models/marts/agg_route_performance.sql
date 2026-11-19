-- Route league table. Routes with few observations are left out so that one
-- unlucky snapshot cannot put a route at the top.
select
    route_id,
    any_value(route_name)                                 as route_name,
    any_value(mode)                                       as mode,
    count(*)                                              as observations,
    count(distinct local_date)                            as days_observed,
    round(median(delay_min), 2)                           as median_delay_min,
    round(quantile_cont(delay_min, 0.9), 2)               as p90_delay_min,
    round(100.0 * avg(is_on_time::int), 1)                as on_time_pct,
    round(100.0 * avg(is_late::int), 1)                   as late_pct
from {{ ref('fct_delay_observations') }}
group by route_id
having count(*) >= 20
