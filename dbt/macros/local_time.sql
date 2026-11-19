{# Convert a unix epoch (seconds) to a local timestamp in the agency's timezone. #}
{% macro local_ts(epoch_col) -%}
    timezone('{{ var("agency_timezone") }}', to_timestamp({{ epoch_col }}))
{%- endmacro %}
