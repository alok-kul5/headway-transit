"""dbt models as Dagster assets. dbt tests become asset checks."""


from collections.abc import Mapping
from typing import Any

import dagster as dg
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from .. import config

dbt_project = DbtProject(project_dir=config.DBT_PROJECT_DIR, profiles_dir=config.DBT_PROJECT_DIR)
# In `dagster dev` this re-parses the project so edits show up; elsewhere the
# manifest must be built first with `dbt parse` (CI and the scheduled workflow do this).
dbt_project.prepare_if_dev()


class Translator(DagsterDbtTranslator):
    def get_asset_key(self, dbt_resource_props: Mapping[str, Any]) -> dg.AssetKey:
        # Sources point at the ingest assets that write them.
        meta = dbt_resource_props.get("meta", {}).get("dagster", {})
        if dbt_resource_props["resource_type"] == "source" and "asset_key" in meta:
            return dg.AssetKey(meta["asset_key"])
        return super().get_asset_key(dbt_resource_props)

    def get_group_name(self, dbt_resource_props: Mapping[str, Any]) -> str | None:
        return dbt_resource_props["fqn"][1] if len(dbt_resource_props["fqn"]) > 2 else "dbt"


@dbt_assets(manifest=dbt_project.manifest_path, project=dbt_project, dagster_dbt_translator=Translator())
def transit_dbt_models(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    # `dbt build` runs models and their tests in DAG order; a failing test
    # skips every model downstream of it, so bad data stops at that layer.
    yield from dbt.cli(["build"], context=context).stream()
