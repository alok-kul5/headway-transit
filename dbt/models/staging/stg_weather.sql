select
    hour_ts::bigint                as hour_ts,
    temperature_2m::double         as temperature_c,
    precipitation::double          as precipitation_mm,
    rain::double                   as rain_mm,
    snowfall::double               as snowfall_cm,
    wind_speed_10m::double         as wind_kmh,
    weather_code::integer          as weather_code,
    case
        when weather_code in (0, 1)                          then 'clear'
        when weather_code in (2, 3)                          then 'cloudy'
        when weather_code in (45, 48)                        then 'fog'
        when weather_code between 51 and 57                  then 'drizzle'
        when weather_code between 61 and 67
          or weather_code between 80 and 82                  then 'rain'
        when weather_code between 71 and 77
          or weather_code in (85, 86)                        then 'snow'
        when weather_code >= 95                              then 'thunderstorm'
        else 'other'
    end                            as condition
from {{ source('raw', 'weather') }}
