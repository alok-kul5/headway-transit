-- Delay under different weather, split by mode, so that a change in which
-- modes are running is not mistaken for a weather effect.
{% set dims = [('precipitation', 'precip_band'), ('temperature', 'temp_band')] %}
{% for name, col in dims %}
select
    '{{ name }}'                                          as dimension,
    {{ col }}                                             as bucket,
    mode,
    count(*)                                              as observations,
    count(distinct strftime(snapshot_local, '%Y-%m-%d %H')) as hours_observed,
    round(median(delay_min), 2)                           as median_delay_min,
    round(quantile_cont(delay_min, 0.9), 2)               as p90_delay_min,
    round(100.0 * avg(is_on_time::int), 1)                as on_time_pct
from {{ ref('fct_delay_observations') }}
group by {{ col }}, mode
{% if not loop.last %}union all{% endif %}
{% endfor %}
