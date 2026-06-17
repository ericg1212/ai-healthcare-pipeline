# Copyright (c) 2026 Eric Grynspan. All rights reserved.
"""
AI enrichment pipeline entry point v0.

Flow: Snowflake staging → enrich → judge → JSON output

Usage:
    python -m ai_layer.run_enrichment --record-type condition --limit 10
    python -m ai_layer.run_enrichment --record-type medication --limit 10
    python -m ai_layer.run_enrichment --record-type both --limit 5

Output: output/enrichment_results_<timestamp>.json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import snowflake.connector
from dotenv import load_dotenv

from ai_layer.enricher import enrich_batch
from ai_layer.judge import judge_batch
from ai_layer.models import ConditionRecord, MedicationRecord
from ai_layer.terminology_validator import log_validation_summary, validate_batch

load_dotenv()

OUTPUT_DIR = Path(__file__).parents[1] / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Snowflake loader — reads from staging views (dbt-built)
# ---------------------------------------------------------------------------

def _get_connection() -> snowflake.connector.SnowflakeConnection:
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema="staging_staging",  # dbt materializes staging views here
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        role=os.environ["SNOWFLAKE_ROLE"],
    )


def load_conditions(limit: int) -> list[ConditionRecord]:
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(  # nosec B608 — limit is a validated int from argparse, not user string input
            f"""
            SELECT patient_id, condition_code, condition_description, onset_date
            FROM stg_condition
            LIMIT {limit}
            """
        )
        rows = cursor.fetchall()
        return [
            ConditionRecord(
                patient_id=row[0],
                condition_code=row[1],
                condition_description=row[2],
                onset_date=row[3],
            )
            for row in rows
        ]
    finally:
        conn.close()


def load_patient_context(patient_ids: list[str]) -> dict:
    """Load co-occurring conditions and medications for a list of patient IDs.

    Returns dict[patient_id -> {conditions: [...], medications: [...]}].
    Used to inject patient context into enrichment prompts.
    """
    if not patient_ids:
        return {}

    conn = _get_connection()
    in_placeholders = ", ".join(["%s"] * len(patient_ids))
    context: dict = {pid: {"conditions": [], "medications": []} for pid in patient_ids}
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT patient_id, condition_code, condition_description
            FROM stg_condition
            WHERE patient_id IN ({in_placeholders})
            ORDER BY onset_date DESC NULLS LAST
            """,
            patient_ids,
        )
        for row in cursor.fetchall():
            pid, code, desc = row
            if pid in context:
                context[pid]["conditions"].append({"code": code, "description": desc})

        cursor.execute(
            f"""
            SELECT patient_id, medication_code, medication_description
            FROM stg_medication
            WHERE patient_id IN ({in_placeholders})
            ORDER BY start_date DESC NULLS LAST
            """,
            patient_ids,
        )
        for row in cursor.fetchall():
            pid, code, desc = row
            if pid in context:
                context[pid]["medications"].append({"code": code, "description": desc})
    finally:
        conn.close()
    return context


def load_medications(limit: int) -> list[MedicationRecord]:
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(  # nosec B608 — limit is a validated int from argparse, not user string input
            f"""
            SELECT patient_id, medication_code, medication_description, start_date
            FROM stg_medication
            LIMIT {limit}
            """
        )
        rows = cursor.fetchall()
        return [
            MedicationRecord(
                patient_id=row[0],
                medication_code=row[1],
                medication_description=row[2],
                start_date=row[3],
            )
            for row in rows
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(record_type: str, limit: int) -> None:
    print(f"Loading {limit} {record_type} record(s) from Snowflake staging...")

    records = []
    if record_type in ("condition", "both"):
        n = limit if record_type == "condition" else max(1, limit // 2)
        records += load_conditions(n)
    if record_type in ("medication", "both"):
        n = limit if record_type == "medication" else max(1, limit // 2)
        records += load_medications(n)

    print(f"Loaded {len(records)} record(s). Validating terminology...")
    validation = validate_batch(records)
    log_validation_summary(validation)

    print("Running enrichment...")
    enrichment_results, enrichment_errors, enrichment_usage = enrich_batch(records)
    print(
        f"Enrichment done: {len(enrichment_results)} ok, "
        f"{len(enrichment_errors)} error(s). "
        f"Cost: ${enrichment_usage['cost_usd']:.4f} "
        f"({enrichment_usage['input_tokens']} input, "
        f"{enrichment_usage['cache_read_tokens']} cached, "
        f"{enrichment_usage['output_tokens']} output tokens)"
    )

    print("Running LLM-as-Judge...")
    verdicts, judge_errors = judge_batch(enrichment_results)
    print(
        f"Judge done: {len(verdicts)} ok, {len(judge_errors)} error(s)."
    )

    disagree_count = sum(1 for v in verdicts if not v.judge_agrees)
    print(f"Judge disagreements: {disagree_count}/{len(verdicts)}")

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    out_path = OUTPUT_DIR / f"enrichment_results_{timestamp}.json"

    output = {
        "run_at": timestamp,
        "record_type": record_type,
        "limit": limit,
        "enrichment_results": [r.model_dump(mode="json") for r in enrichment_results],
        "enrichment_errors": enrichment_errors,
        "enrichment_usage": enrichment_usage,
        "judge_verdicts": [v.model_dump(mode="json") for v in verdicts],
        "judge_errors": judge_errors,
    }

    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"Results written to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI enrichment pipeline v0")
    parser.add_argument(
        "--record-type",
        choices=["condition", "medication", "both"],
        default="both",
    )
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    run(args.record_type, args.limit)
