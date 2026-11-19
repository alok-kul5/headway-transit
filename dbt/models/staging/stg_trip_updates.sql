-- One row per trip per snapshot, typed, with the predicted delay at its next stop.
with src as (
    select * from {{ source('raw', 'trip_updates') }}
)

select
    snapshot_ts::bigint                                   as snapshot_ts,
    trip_id,
    route_id,
    direction_id::integer                                 as direction_id,
    strptime(start_date, '%Y%m%d')::date                  as service_date,
    trip_schedule_relationship,
    vehicle_id,
    stop_id,
    stop_sequence::integer                                as stop_sequence,
    predicted_ts::bigint                                  as predicted_ts,
    scheduled_ts::bigint                                  as scheduled_ts,
    predicted_ts::bigint - snapshot_ts::bigint            as horizon_s,
    predicted_ts::bigint - scheduled_ts::bigint           as delay_s
from src
qualify row_number() over (partition by snapshot_ts, trip_id order by predicted_ts) = 1
