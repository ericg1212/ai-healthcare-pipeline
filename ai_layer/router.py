"""
Gold routing logic — determines where each enriched record lands.

Two signals compared after parallel execution:
  - Rules Engine: HIGH if flags_triggered >= 2 OR medication_appropriateness fires (Cat 3)
  - Enricher:     HIGH if overall_confidence >= CONFIDENCE_THRESHOLD

Three output states:
  GOLD_CLEAN               — both signals agree (HIGH+HIGH or LOW+LOW)
  GOLD_REVIEW_CONFLICT     — signals disagree, enricher confidence >= threshold
  GOLD_REVIEW_LOW_CONFIDENCE — signals disagree, enricher confidence < threshold
                              (low confidence = abstention; Rules Engine deferred)
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ai_layer.models import EnrichmentResult, JudgeVerdict
from ai_layer.rules_engine import RulesEngineResult

CONFIDENCE_THRESHOLD = 0.5
COST_PER_RECORD_USD = 0.003  # Sonnet with prompt caching, approximate


RoutingDecisionLabel = Literal[
    "GOLD_CLEAN",
    "GOLD_REVIEW_CONFLICT",
    "GOLD_REVIEW_LOW_CONFIDENCE",
]


class RoutingDecision(BaseModel):
    patient_id: str
    record_code: str
    record_type: Literal["condition", "medication"]
    rules_risk: Literal["HIGH", "LOW"]
    enricher_confidence: float = Field(ge=0.0, le=1.0)
    enricher_risk: Literal["HIGH", "LOW"]
    judge_agrees: bool
    corrected_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    routing_decision: RoutingDecisionLabel
    review_flag: bool
    routing_reason: str
    cost_usd: float = COST_PER_RECORD_USD
    processed_at: datetime = Field(default_factory=datetime.utcnow)


def apply_rules_risk(rules: RulesEngineResult) -> Literal["HIGH", "LOW"]:
    """HIGH if >= 2 flags OR any Cat 3 (medication_appropriateness) fires."""
    if rules.medication_appropriateness_flag or len(rules.flags_triggered) >= 2:
        return "HIGH"
    return "LOW"


def route(
    enrichment: EnrichmentResult,
    verdict: JudgeVerdict,
    rules: RulesEngineResult,
) -> RoutingDecision:
    """Apply routing logic and return a RoutingDecision."""
    rules_risk = apply_rules_risk(rules)
    enricher_risk: Literal["HIGH", "LOW"] = (
        "HIGH" if enrichment.overall_confidence >= CONFIDENCE_THRESHOLD else "LOW"
    )

    if rules_risk == enricher_risk:
        return RoutingDecision(
            patient_id=enrichment.patient_id,
            record_code=enrichment.record_code,
            record_type=enrichment.record_type,
            rules_risk=rules_risk,
            enricher_confidence=enrichment.overall_confidence,
            enricher_risk=enricher_risk,
            judge_agrees=verdict.judge_agrees,
            corrected_confidence=verdict.corrected_confidence,
            routing_decision="GOLD_CLEAN",
            review_flag=False,
            routing_reason=f"Both signals agree: {rules_risk}",
        )

    # Signals conflict — use enricher confidence to decide
    if enrichment.overall_confidence >= CONFIDENCE_THRESHOLD:
        return RoutingDecision(
            patient_id=enrichment.patient_id,
            record_code=enrichment.record_code,
            record_type=enrichment.record_type,
            rules_risk=rules_risk,
            enricher_confidence=enrichment.overall_confidence,
            enricher_risk=enricher_risk,
            judge_agrees=verdict.judge_agrees,
            corrected_confidence=verdict.corrected_confidence,
            routing_decision="GOLD_REVIEW_CONFLICT",
            review_flag=True,
            routing_reason=(
                f"Signal conflict: Rules={rules_risk}, Enricher={enricher_risk} "
                f"(confidence {enrichment.overall_confidence:.2f} >= threshold {CONFIDENCE_THRESHOLD})"
            ),
        )

    return RoutingDecision(
        patient_id=enrichment.patient_id,
        record_code=enrichment.record_code,
        record_type=enrichment.record_type,
        rules_risk=rules_risk,
        enricher_confidence=enrichment.overall_confidence,
        enricher_risk=enricher_risk,
        judge_agrees=verdict.judge_agrees,
        corrected_confidence=verdict.corrected_confidence,
        routing_decision="GOLD_REVIEW_LOW_CONFIDENCE",
        review_flag=True,
        routing_reason=(
            f"Low enricher confidence ({enrichment.overall_confidence:.2f} < threshold {CONFIDENCE_THRESHOLD}): "
            f"Rules Engine deferred, routing to review"
        ),
    )
