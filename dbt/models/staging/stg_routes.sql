select
    route_id,
    coalesce(nullif(route_short_name, ''), route_long_name)   as route_name,
    route_long_name,
    route_type::integer                                        as route_type,
    case route_type::integer
        when 0 then 'Light rail'
        when 1 then 'Subway'
        when 2 then 'Commuter rail'
        when 3 then 'Bus'
        when 4 then 'Ferry'
        else 'Other'
    end                                                        as mode,
    '#' || coalesce(nullif(route_color, ''), '888888')         as route_color
from {{ source('raw', 'gtfs_routes') }}
