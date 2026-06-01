"""
Dagster software-defined assets — AI Healthcare Pipeline v0.

Asset graph (left to right):
  fhir_s3_upload
    └── snowflake_raw_tables
          └── dbt_staging_models
                ├── condition_enrichments
                ├── medication_enrichments
                      └── ai_enrichment_verdicts
                              └── gold_routing
                                    └── dbt_mart_models

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
# Helper: shared enrichment logic for condition + medication assets
# ---------------------------------------------------------------------------

def _run_enrichment_asset(context, record_type: str, load_fn, prefix: str) -> MaterializeResult:
    from ai_layer.enricher import enrich_batch

    limit = int(os.getenv("ENRICHMENT_LIMIT", "50"))
    records = load_fn(limit)
    context.log.info(f"Loaded {len(records)} {record_type} records")

    results, errors, usage = enrich_batch(records)
    context.log.info(
        f"Enriched {len(results)} ok, {len(errors)} errors — "
        f"${usage['cost_usd']:.4f} "
        f"({usage['input_tokens']} input, {usage['cache_read_tokens']} cached, "
        f"{usage['output_tokens']} output tokens)"
    )
    if errors:
        context.log.warning(f"Enrichment errors: {errors}")

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    out_path = OUTPUT_DIR / f"{prefix}_{timestamp}.json"
    out_path.write_text(
        json.dumps([r.model_dump(mode="json") for r in results], indent=2, default=str)
    )

    return MaterializeResult(
        metadata={
            "records_loaded": MetadataValue.int(len(records)),
            "records_enriched": MetadataValue.int(len(results)),
            "errors": MetadataValue.int(len(errors)),
            "output_file": MetadataValue.path(str(out_path)),
            "input_tokens": MetadataValue.int(usage["input_tokens"]),
            "cache_read_tokens": MetadataValue.int(usage["cache_read_tokens"]),
            "output_tokens": MetadataValue.int(usage["output_tokens"]),
            "cost_usd": MetadataValue.float(round(usage["cost_usd"], 4)),
        }
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
    from ai_layer.run_enrichment import load_conditions
    return _run_enrichment_asset(context, "condition", load_conditions, "condition_enrichments")


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
    from ai_layer.run_enrichment import load_medications
    return _run_enrichment_asset(context, "medication", load_medications, "medication_enrichments")


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
# Asset 7: Gold routing — Rules Engine + routing logic → Snowflake
# ---------------------------------------------------------------------------

@asset(
    deps=["ai_enrichment_verdicts"],
    group_name="gold",
    compute_kind="python",
)
def gold_routing(context) -> MaterializeResult:
    """Run Rules Engine + routing on enrichment results. Writes GOLD_ROUTING_STAGE to Snowflake."""
    import snowflake.connector

    from ai_layer.models import EnrichmentResult, JudgeVerdict
    from ai_layer.router import route
    from ai_layer.rules_engine import RulesEngine
    from ai_layer.run_enrichment import load_conditions, load_medications

    engine = RulesEngine()

    # Load original staging records to run Rules Engine
    limit = int(os.getenv("ENRICHMENT_LIMIT", "50"))
    cond_records = load_conditions(limit)
    med_records = load_medications(limit)
    all_records = cond_records + med_records

    rules_by_key: dict[tuple[str, str], object] = {
        (r.patient_id, getattr(r, "condition_code", None) or getattr(r, "medication_code", None)): engine.evaluate(r)
        for r in all_records
    }

    # Load latest enrichment files
    def _load_latest(prefix: str, model_cls):
        files = sorted(OUTPUT_DIR.glob(f"{prefix}_*.json"), reverse=True)
        if not files:
            return []
        raw = json.loads(files[0].read_text())
        return [model_cls(**r) for r in raw]

    enrichments: list[EnrichmentResult] = (
        _load_latest("condition_enrichments", EnrichmentResult)
        + _load_latest("medication_enrichments", EnrichmentResult)
    )
    verdicts: list[JudgeVerdict] = _load_latest("judge_verdicts", JudgeVerdict)

    verdicts_by_key = {(v.patient_id, v.record_code): v for v in verdicts}

    decisions = []
    skipped = 0
    for enrichment in enrichments:
        key = (enrichment.patient_id, enrichment.record_code)
        verdict = verdicts_by_key.get(key)
        rules = rules_by_key.get(key)
        if verdict is None or rules is None:
            skipped += 1
            continue
        decisions.append(route(enrichment, verdict, rules))

    context.log.info(
        f"Routed {len(decisions)} records "
        f"({skipped} skipped — no matching verdict or rules result)"
    )

    # Write to Snowflake GOLD_ROUTING_STAGE
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema="STAGING_STAGING",
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        role=os.environ["SNOWFLAKE_ROLE"],
    )
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS GOLD_ROUTING_STAGE (
                patient_id      VARCHAR,
                record_code     VARCHAR,
                record_type     VARCHAR,
                rules_risk      VARCHAR,
                enricher_confidence FLOAT,
                enricher_risk   VARCHAR,
                judge_agrees    BOOLEAN,
                corrected_confidence FLOAT,
                routing_decision VARCHAR,
                review_flag     BOOLEAN,
                routing_reason  VARCHAR,
                cost_usd        FLOAT,
                processed_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
        """)
        cursor.execute("TRUNCATE TABLE GOLD_ROUTING_STAGE")

        rows = [
            (
                d.patient_id, d.record_code, d.record_type,
                d.rules_risk, d.enricher_confidence, d.enricher_risk,
                d.judge_agrees, d.corrected_confidence,
                d.routing_decision, d.review_flag, d.routing_reason,
                d.cost_usd,
            )
            for d in decisions
        ]
        cursor.executemany(
            """
            INSERT INTO GOLD_ROUTING_STAGE (
                patient_id, record_code, record_type,
                rules_risk, enricher_confidence, enricher_risk,
                judge_agrees, corrected_confidence,
                routing_decision, review_flag, routing_reason,
                cost_usd
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    review_count = sum(1 for d in decisions if d.review_flag)
    clean_count = len(decisions) - review_count
    total_cost = sum(d.cost_usd for d in decisions)

    return MaterializeResult(
        metadata={
            "total_routed": MetadataValue.int(len(decisions)),
            "gold_clean": MetadataValue.int(clean_count),
            "gold_review": MetadataValue.int(review_count),
            "skipped": MetadataValue.int(skipped),
            "total_cost_usd": MetadataValue.float(round(total_cost, 4)),
        }
    )


# ---------------------------------------------------------------------------
# Asset 8: dbt mart models — builds mart_patient_risk_scores from GOLD_ROUTING_STAGE
# ---------------------------------------------------------------------------

@asset(
    deps=["gold_routing"],
    group_name="gold",
    compute_kind="dbt",
)
def dbt_mart_models(context) -> MaterializeResult:
    """Run dbt marts layer (mart_patient_risk_scores)."""
    result = subprocess.run(
        [
            sys.executable, "-m", "dbt", "run",
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
