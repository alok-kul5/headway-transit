-- Keep only rows that tell us a vehicle's current delay:
--   * the trip runs to a published schedule (so "late" means something),
--   * we found its scheduled time,
--   * the prediction is for a stop it reaches soon (a far-off prediction is a guess).
select *
from {{ ref('stg_trip_updates') }}
where trip_schedule_relationship = 'SCHEDULED'
  and scheduled_ts is not null
  and horizon_s between -120 and {{ var('max_horizon_s') }}
  -- More than 4 hours off is a data problem (wrong service day, etc.), not a delay.
  and abs(delay_s) <= 4 * 3600
