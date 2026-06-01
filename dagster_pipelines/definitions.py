from dagster import Definitions

from dagster_pipelines.assets import (
    ai_enrichment_verdicts,
    condition_enrichments,
    dbt_mart_models,
    dbt_staging_models,
    fhir_s3_upload,
    gold_review_routing,
    medication_enrichments,
    snowflake_raw_tables,
)

defs = Definitions(
    assets=[
        fhir_s3_upload,
        snowflake_raw_tables,
        dbt_staging_models,
        condition_enrichments,
        medication_enrichments,
        ai_enrichment_verdicts,
        gold_review_routing,
        dbt_mart_models,
    ],
)
