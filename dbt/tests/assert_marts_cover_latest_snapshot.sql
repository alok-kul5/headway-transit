{{ config(meta={"dagster": {"ref": {"name": "fct_delay_observations"}}}) }}
-- The fact table must include the newest snapshot that had any usable delay
-- observations. Catches joins that silently drop data.
with latest as (
    select max(snapshot_ts) as ts from {{ ref('int_delay_observations') }}
)
select latest.ts
from latest
where latest.ts is not null
  and not exists (select 1 from {{ ref('fct_delay_observations') }} f where f.snapshot_ts = latest.ts)
