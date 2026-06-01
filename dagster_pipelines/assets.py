"""
Dagster software-defined assets — AI Healthcare Pipeline v0.

Asset graph (left to right):
  fhir_s3_upload
    └── snowflake_raw_tables
          └── dbt_staging_models
                ├── condition_enrichments
                ├── medication_enrichments
                      └── ai_enrichment_verdicts
                              └── gold_review_routing
                                        └── dbt_mart_models

Run locally:
  dagster dev
  then Materialize All in the UI.
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
            str(Path(sys.executable).parent / "dbt"), "run",
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
    compute_kind="llm",
)
def condition_enrichments(context) -> MaterializeResult:
    """Run LLM enrichment on stg_condition records. Writes JSON to output/."""
    from ai_layer.enricher import enrich_batch
    from ai_layer.run_enrichment import load_conditions, load_patient_context

    limit = int(os.getenv("ENRICHMENT_LIMIT", "50"))
    records = load_conditions(limit)
    context.log.info(f"Loaded {len(records)} condition records")

    patient_ids = [r.patient_id for r in records]
    patient_ctx = load_patient_context(patient_ids)
    context.log.info(f"Loaded patient context for {len(patient_ctx)} patients")

    results, errors = enrich_batch(records, patient_context=patient_ctx)
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
    compute_kind="llm",
)
def medication_enrichments(context) -> MaterializeResult:
    """Run LLM enrichment on stg_medication records. Writes JSON to output/."""
    from ai_layer.enricher import enrich_batch
    from ai_layer.run_enrichment import load_medications, load_patient_context

    limit = int(os.getenv("ENRICHMENT_LIMIT", "50"))
    records = load_medications(limit)
    context.log.info(f"Loaded {len(records)} medication records")

    patient_ids = [r.patient_id for r in records]
    patient_ctx = load_patient_context(patient_ids)
    context.log.info(f"Loaded patient context for {len(patient_ctx)} patients")

    results, errors = enrich_batch(records, patient_context=patient_ctx)
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
    compute_kind="llm",
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


# ---------------------------------------------------------------------------
# Asset 7: Gold/Review routing gate
# ---------------------------------------------------------------------------

@asset(
    deps=["ai_enrichment_verdicts"],
    group_name="gold_layer",
    compute_kind="python",
)
def gold_review_routing(context) -> MaterializeResult:
    """Route enriched records to Gold (clean) or Review (conflict/low-confidence).

    Loads the latest enrichment + verdict JSON files, runs the rules engine,
    and writes all records to Snowflake GOLD.GOLD_RECORDS with a gold_status.
    """
    import snowflake.connector
    from ai_layer.models import EnrichmentResult, JudgeVerdict
    from ai_layer.router import route_batch

    def _load_latest(prefix: str) -> list:
        files = sorted(OUTPUT_DIR.glob(f"{prefix}_*.json"), reverse=True)
        if not files:
            return []
        return json.loads(files[0].read_text())

    enrichment_raw = _load_latest("condition_enrichments") + _load_latest("medication_enrichments")
    verdict_raw = _load_latest("judge_verdicts")

    enrichments = [EnrichmentResult(**r) for r in enrichment_raw]
    verdicts = [JudgeVerdict(**v) for v in verdict_raw]
    context.log.info(f"Routing {len(enrichments)} enrichments against {len(verdicts)} verdicts")

    gold_records = route_batch(enrichments, verdicts)
    context.log.info(f"Routed {len(gold_records)} records")

    counts = {}
    for r in gold_records:
        counts[r.gold_status] = counts.get(r.gold_status, 0) + 1
    context.log.info(f"Gold status counts: {counts}")

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        role=os.environ["SNOWFLAKE_ROLE"],
    )
    try:
        cur = conn.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS GOLD")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS GOLD.GOLD_RECORDS (
                patient_id        VARCHAR,
                record_type       VARCHAR,
                record_code       VARCHAR,
                record_description VARCHAR,
                overall_confidence FLOAT,
                gold_status       VARCHAR,
                review_reason     VARCHAR,
                flags_triggered   VARCHAR,
                judge_agrees      BOOLEAN,
                corrected_confidence FLOAT,
                routed_at         TIMESTAMP_NTZ
            )
        """)
        cur.execute("TRUNCATE TABLE GOLD.GOLD_RECORDS")
        rows = [
            (
                r.patient_id,
                r.record_type,
                r.record_code,
                r.record_description,
                r.overall_confidence,
                r.gold_status,
                r.review_reason,
                ",".join(r.flags_triggered) if r.flags_triggered else None,
                r.judge_agrees,
                r.corrected_confidence,
                r.routed_at,
            )
            for r in gold_records
        ]
        cur.executemany(
            "INSERT INTO GOLD.GOLD_RECORDS VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )
        context.log.info(f"Wrote {len(rows)} rows to GOLD.GOLD_RECORDS")
    finally:
        conn.close()

    return MaterializeResult(
        metadata={
            "total_routed": MetadataValue.int(len(gold_records)),
            "enriched_clean": MetadataValue.int(counts.get("enriched_clean", 0)),
            "enriched_review_conflict": MetadataValue.int(counts.get("enriched_review_conflict", 0)),
            "enriched_review_low_confidence": MetadataValue.int(counts.get("enriched_review_low_confidence", 0)),
        }
    )


# ---------------------------------------------------------------------------
# Asset 8: dbt mart models (gold_records + review_records)
# ---------------------------------------------------------------------------

@asset(
    deps=["gold_review_routing"],
    group_name="gold_layer",
    compute_kind="dbt",
)
def dbt_mart_models(context) -> MaterializeResult:
    """Run dbt marts layer (gold_records, review_records) against GOLD.GOLD_RECORDS."""
    result = subprocess.run(
        [
            str(Path(sys.executable).parent / "dbt"), "run",
            "--select", "marts",
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

    completed = result.stdout.count("OK created sql table")
    return MaterializeResult(
        metadata={"models_materialized": MetadataValue.int(completed)}
    )
