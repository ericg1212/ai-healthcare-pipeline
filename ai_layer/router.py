"""
Gold/Review routing gate.

Combines EnrichmentResult + JudgeVerdict + RulesEngine to assign each record
one of three Gold states:

  enriched_clean               — judge agrees, no rules flags, confidence >= threshold
  enriched_review_conflict     — judge disagrees OR rules engine flagged something
  enriched_review_low_confidence — judge agrees, no flags, but confidence < threshold
"""

from __future__ import annotations

from ai_layer.models import (
    ConditionRecord,
    EnrichmentResult,
    GoldRecord,
    JudgeVerdict,
    MedicationRecord,
)
from ai_layer.rules_engine import RulesEngine

CONFIDENCE_THRESHOLD = 0.55

_engine = RulesEngine()


def route(enrichment: EnrichmentResult, verdict: JudgeVerdict) -> GoldRecord:
    if enrichment.record_type == "condition":
        record = ConditionRecord(
            patient_id=enrichment.patient_id,
            condition_code=enrichment.record_code,
            condition_description=enrichment.record_description,
            onset_date=enrichment.onset_date,
        )
    else:
        record = MedicationRecord(
            patient_id=enrichment.patient_id,
            medication_code=enrichment.record_code,
            medication_description=enrichment.record_description,
        )

    rules_result = _engine.evaluate(record)
    has_conflict = not verdict.judge_agrees or bool(rules_result.flags_triggered)

    if has_conflict:
        gold_status = "enriched_review_conflict"
        reasons = []
        if not verdict.judge_agrees and verdict.disagreement_reason:
            reasons.append(verdict.disagreement_reason)
        if rules_result.flags_triggered:
            reasons.append(f"rules: {', '.join(rules_result.flags_triggered)}")
        review_reason = "; ".join(reasons) or "conflict detected"
    elif enrichment.overall_confidence < CONFIDENCE_THRESHOLD:
        gold_status = "enriched_review_low_confidence"
        review_reason = f"confidence {enrichment.overall_confidence:.2f} below {CONFIDENCE_THRESHOLD}"
    else:
        gold_status = "enriched_clean"
        review_reason = None

    return GoldRecord(
        patient_id=enrichment.patient_id,
        record_type=enrichment.record_type,
        record_code=enrichment.record_code,
        record_description=enrichment.record_description,
        overall_confidence=enrichment.overall_confidence,
        gold_status=gold_status,
        review_reason=review_reason,
        flags_triggered=rules_result.flags_triggered,
        judge_agrees=verdict.judge_agrees,
        corrected_confidence=verdict.corrected_confidence,
    )


def route_batch(
    enrichments: list[EnrichmentResult],
    verdicts: list[JudgeVerdict],
) -> list[GoldRecord]:
    verdict_map = {(v.patient_id, v.record_code): v for v in verdicts}
    gold_records = []
    for e in enrichments:
        v = verdict_map.get((e.patient_id, e.record_code))
        if v is None:
            continue
        gold_records.append(route(e, v))
    return gold_records
