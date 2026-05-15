"""
Dagster software-defined assets — AI Healthcare Pipeline v0.

Asset graph (left to right):
  fhir_s3_upload
    └── snowflake_raw_tables
          └── dbt_staging_models
                ├── condition_enrichments
                ├── medication_enrichments
                      └── ai_enrichment_verdicts

Run locally:
  dagster dev -m dagster_pipelines
  then Materialize All in the UI, or:
  dagster asset materialize -m dagster_pipelines --select "*"
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dagster import MaterializeResult, MetadataValue, asset
from dotenv import load_dotenv

load_dotenv()

DBT_PROJECT_DIR = Path(__file__).parents[1] / "dbt_pipeline"
OUTPUT_DIR = Path(__file__).parents[1] / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Asset 1: Upload FHIR bundles to S3
# ---------------------------------------------------------------------------

@asset(group_name="ingestion", compute_kind="python")
def fhir_s3_upload(context) -> MaterializeResult:
    """Upload synthetic FHIR JSON bundles from synthetic_data/fhir/ to S3."""
    from data_ingestion.load_to_snowflake import upload_to_s3

    fhir_dir = Path(__file__).parents[1] / "synthetic_data" / "fhir"
    count = upload_to_s3(fhir_dir)
    return MaterializeResult(
        metadata={"files_uploaded": MetadataValue.int(count)}
    )


# ---------------------------------------------------------------------------
# Asset 2: Parse FHIR + load to Snowflake RAW
# ---------------------------------------------------------------------------

@asset(
    deps=["fhir_s3_upload"],
    group_name="ingestion",
    compute_kind="snowflake",
)
def snowflake_raw_tables(context) -> MaterializeResult:
    """Parse FHIR bundles and load all four RAW tables in Snowflake."""
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / "data_ingestion"))

    from data_ingestion.fhir_parser import parse_all
    from data_ingestion.load_to_snowflake import (
        create_tables,
        get_snowflake_conn,
        load_table,
    )

    fhir_dir = Path(__file__).parents[1] / "synthetic_data" / "fhir"
    data = parse_all(fhir_dir)

    conn = get_snowflake_conn()
    totals: dict[str, int] = {}
    try:
        create_tables(conn)
        totals["PERSON"] = load_table(conn, "PERSON", data["person"])
        totals["CONDITION"] = load_table(conn, "CONDITION", data["conditions"])
        totals["MEDICATION"] = load_table(conn, "MEDICATION", data["medications"])
        totals["ENCOUNTER"] = load_table(conn, "ENCOUNTER", data["encounters"])
    finally:
        conn.close()

    context.log.info(f"Loaded rows: {totals}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in totals.items()}
    )


# ---------------------------------------------------------------------------
# Asset 3: Run dbt staging models
# ---------------------------------------------------------------------------

@asset(
    deps=["snowflake_raw_tables"],
    group_name="transformation",
    compute_kind="dbt",
)
def dbt_staging_models(context) -> MaterializeResult:
    """Run dbt staging layer (stg_person, stg_condition, stg_medication, stg_encounter)."""
    result = subprocess.run(
        [
            sys.executable, "-m", "dbt", "run",
            "--select", "staging",
            "--project-dir", str(DBT_PROJECT_DIR),
            "--profiles-dir", str(DBT_PROJECT_DIR),
        ],
        capture_output=True,
        text=True,
        cwd=str(DBT_PROJECT_DIR),
    )

    context.log.info(result.stdout)
    if result.returncode != 0:
        context.log.error(result.stderr)
        raise RuntimeError(f"dbt run failed:\n{result.stderr}")

    # Count models completed from dbt output
    completed = result.stdout.count("OK created sql view")
    return MaterializeResult(
        metadata={"models_materialized": MetadataValue.int(completed)}
    )


# ---------------------------------------------------------------------------
# Asset 4: Enrich condition records
# ---------------------------------------------------------------------------

@asset(
    deps=["dbt_staging_models"],
    group_name="ai_enrichment",
    compute_kind="claude",
)
def condition_enrichments(context) -> MaterializeResult:
    """Run Claude enrichment on stg_condition records. Writes JSON to output/."""
    from ai_layer.enricher import enrich_batch
    from ai_layer.run_enrichment import load_conditions

    limit = int(os.getenv("ENRICHMENT_LIMIT", "50"))
    records = load_conditions(limit)
    context.log.info(f"Loaded {len(records)} condition records")

    results, errors = enrich_batch(records)
    context.log.info(f"Enriched {len(results)} ok, {len(errors)} errors")

    if errors:
        context.log.warning(f"Enrichment errors: {errors}")

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    out_path = OUTPUT_DIR / f"condition_enrichments_{timestamp}.json"
    out_path.write_text(
        json.dumps([r.model_dump(mode="json") for r in results], indent=2, default=str)
    )

    return MaterializeResult(
        metadata={
            "records_loaded": MetadataValue.int(len(records)),
            "records_enriched": MetadataValue.int(len(results)),
            "errors": MetadataValue.int(len(errors)),
            "output_file": MetadataValue.path(str(out_path)),
        }
    )


# ---------------------------------------------------------------------------
# Asset 5: Enrich medication records
# ---------------------------------------------------------------------------

@asset(
    deps=["dbt_staging_models"],
    group_name="ai_enrichment",
    compute_kind="claude",
)
def medication_enrichments(context) -> MaterializeResult:
    """Run Claude enrichment on stg_medication records. Writes JSON to output/."""
    from ai_layer.enricher import enrich_batch
    from ai_layer.run_enrichment import load_medications

    limit = int(os.getenv("ENRICHMENT_LIMIT", "50"))
    records = load_medications(limit)
    context.log.info(f"Loaded {len(records)} medication records")

    results, errors = enrich_batch(records)
    context.log.info(f"Enriched {len(results)} ok, {len(errors)} errors")

    if errors:
        context.log.warning(f"Enrichment errors: {errors}")

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    out_path = OUTPUT_DIR / f"medication_enrichments_{timestamp}.json"
    out_path.write_text(
        json.dumps([r.model_dump(mode="json") for r in results], indent=2, default=str)
    )

    return MaterializeResult(
        metadata={
            "records_loaded": MetadataValue.int(len(records)),
            "records_enriched": MetadataValue.int(len(results)),
            "errors": MetadataValue.int(len(errors)),
            "output_file": MetadataValue.path(str(out_path)),
        }
    )


# ---------------------------------------------------------------------------
# Asset 6: LLM-as-Judge verdicts (depends on both enrichment assets)
# ---------------------------------------------------------------------------

@asset(
    deps=["condition_enrichments", "medication_enrichments"],
    group_name="ai_enrichment",
    compute_kind="claude",
)
def ai_enrichment_verdicts(context) -> MaterializeResult:
    """Run LLM-as-Judge on the latest condition + medication enrichment files."""
    from ai_layer.judge import judge_batch
    from ai_layer.models import EnrichmentResult

    # Load the most recently written enrichment files
    def _load_latest(prefix: str) -> list[EnrichmentResult]:
        files = sorted(OUTPUT_DIR.glob(f"{prefix}_*.json"), reverse=True)
        if not files:
            return []
        raw = json.loads(files[0].read_text())
        return [EnrichmentResult(**r) for r in raw]

    all_results = _load_latest("condition_enrichments") + _load_latest("medication_enrichments")
    context.log.info(f"Judging {len(all_results)} enrichment results")

    verdicts, errors = judge_batch(all_results)
    disagree = sum(1 for v in verdicts if not v.judge_agrees)
    context.log.info(f"Judge: {len(verdicts)} ok, {disagree} disagreements, {len(errors)} errors")

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    out_path = OUTPUT_DIR / f"judge_verdicts_{timestamp}.json"
    out_path.write_text(
        json.dumps([v.model_dump(mode="json") for v in verdicts], indent=2, default=str)
    )

    return MaterializeResult(
        metadata={
            "total_judged": MetadataValue.int(len(verdicts)),
            "disagreements": MetadataValue.int(disagree),
            "agreement_rate": MetadataValue.float(
                (len(verdicts) - disagree) / len(verdicts) if verdicts else 0.0
            ),
            "errors": MetadataValue.int(len(errors)),
            "output_file": MetadataValue.path(str(out_path)),
        }
    )
