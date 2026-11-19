-- One row per vehicle per snapshot: its delay, where it is, and the weather that hour.
with obs as (
    select * from {{ ref('int_delay_observations') }}
),
routes as (
    select * from {{ ref('stg_routes') }}
),
stops as (
    select * from {{ ref('stg_stops') }}
),
weather as (
    select * from {{ ref('stg_weather') }}
)

select
    obs.snapshot_ts,
    {{ local_ts('obs.snapshot_ts') }}                           as snapshot_local,
    cast({{ local_ts('obs.snapshot_ts') }} as date)             as local_date,
    extract(hour from {{ local_ts('obs.snapshot_ts') }})::int   as local_hour,
    extract(isodow from {{ local_ts('obs.snapshot_ts') }})::int as local_dow,
    extract(isodow from {{ local_ts('obs.snapshot_ts') }}) >= 6 as is_weekend,
    obs.trip_id,
    obs.route_id,
    coalesce(routes.route_name, obs.route_id)                   as route_name,
    coalesce(routes.mode, 'Other')                              as mode,
    obs.direction_id,
    obs.stop_id,
    stops.stop_name,
    obs.delay_s,
    round(obs.delay_s / 60.0, 2)                                as delay_min,
    obs.delay_s between -{{ var('on_time_early_s') }} and {{ var('on_time_late_s') }} as is_on_time,
    obs.delay_s > {{ var('on_time_late_s') }}                   as is_late,
    weather.temperature_c,
    weather.precipitation_mm,
    weather.snowfall_cm,
    weather.wind_kmh,
    weather.condition                                           as weather_condition,
    case
        when weather.precipitation_mm is null then 'unknown'
        when weather.snowfall_cm > 0          then 'snow'
        when weather.precipitation_mm = 0     then 'dry'
        when weather.precipitation_mm < 1     then 'light rain'
        else 'heavy rain'
    end                                                         as precip_band,
    case
        when weather.temperature_c is null then 'unknown'
        when weather.temperature_c < 0     then 'below 0 C'
        when weather.temperature_c < 10    then '0 to 10 C'
        when weather.temperature_c < 20    then '10 to 20 C'
        else '20 C and up'
    end                                                         as temp_band
from obs
left join routes  on routes.route_id = obs.route_id
left join stops   on stops.stop_id = obs.stop_id
left join weather on weather.hour_ts = obs.snapshot_ts - (obs.snapshot_ts % 3600)
