select * from {{ ref('agg_route_performance') }} where on_time_pct < 0 or on_time_pct > 100
