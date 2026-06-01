"""Tests for Gold routing logic."""

from datetime import date, datetime

import pytest

from ai_layer.models import CategoryScore, EnrichmentResult, JudgeVerdict
from ai_layer.router import CONFIDENCE_THRESHOLD, apply_rules_risk, route
from ai_layer.rules_engine import RulesEngine, RulesEngineResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_enrichment(patient_id: str, code: str, confidence: float) -> EnrichmentResult:
    score = CategoryScore(score=confidence, rationale="test")
    return EnrichmentResult(
        patient_id=patient_id,
        record_type="condition",
        record_code=code,
        record_description="test condition",
        diagnosis_specificity=score,
        clinical_urgency=score,
        coding_accuracy=score,
        medication_appropriateness=score,
        drug_condition_alignment=score,
        comorbidity_risk=score,
        overall_confidence=confidence,
        enriched_at=datetime.utcnow(),
    )


def _make_verdict(patient_id: str, code: str, agrees: bool) -> JudgeVerdict:
    return JudgeVerdict(
        patient_id=patient_id,
        record_code=code,
        record_type="condition",
        judge_agrees=agrees,
        disagreement_reason="test disagreement" if not agrees else None,
        judged_at=datetime.utcnow(),
    )


def _make_rules_result(patient_id: str, flags: list[str]) -> RulesEngineResult:
    return RulesEngineResult(
        patient_id=patient_id,
        diagnosis_specificity_flag="diagnosis_specificity" in flags,
        clinical_urgency_flag="clinical_urgency" in flags,
        coding_accuracy_flag="coding_accuracy" in flags,
        medication_appropriateness_flag="medication_appropriateness" in flags,
        drug_condition_alignment_flag="drug_condition_alignment" in flags,
        comorbidity_risk_flag="comorbidity_risk" in flags,
        flags_triggered=flags,
    )


# ---------------------------------------------------------------------------
# apply_rules_risk
# ---------------------------------------------------------------------------

def test_rules_risk_high_via_count():
    result = _make_rules_result("P1", ["diagnosis_specificity", "clinical_urgency"])
    assert apply_rules_risk(result) == "HIGH"


def test_rules_risk_high_via_cat3():
    # Cat 3 override — single medication_appropriateness flag = HIGH
    result = _make_rules_result("P1", ["medication_appropriateness"])
    assert apply_rules_risk(result) == "HIGH"


def test_rules_risk_low():
    result = _make_rules_result("P1", ["diagnosis_specificity"])  # 1 flag, not Cat 3
    assert apply_rules_risk(result) == "LOW"


def test_rules_risk_low_no_flags():
    result = _make_rules_result("P1", [])
    assert apply_rules_risk(result) == "LOW"


# ---------------------------------------------------------------------------
# route — three Gold states
# ---------------------------------------------------------------------------

def test_route_gold_clean_both_high():
    enrichment = _make_enrichment("P1", "E11.9", confidence=0.8)
    verdict = _make_verdict("P1", "E11.9", agrees=True)
    rules = _make_rules_result("P1", ["diagnosis_specificity", "clinical_urgency"])

    decision = route(enrichment, verdict, rules)

    assert decision.routing_decision == "GOLD_CLEAN"
    assert decision.review_flag is False
    assert decision.rules_risk == "HIGH"
    assert decision.enricher_risk == "HIGH"


def test_route_gold_clean_both_low():
    enrichment = _make_enrichment("P1", "E11.9", confidence=0.3)
    verdict = _make_verdict("P1", "E11.9", agrees=True)
    rules = _make_rules_result("P1", [])

    decision = route(enrichment, verdict, rules)

    assert decision.routing_decision == "GOLD_CLEAN"
    assert decision.review_flag is False
    assert decision.rules_risk == "LOW"
    assert decision.enricher_risk == "LOW"


def test_route_gold_review_conflict():
    # Rules LOW but enricher HIGH (confidence >= threshold) → genuine conflict
    enrichment = _make_enrichment("P1", "E11.9", confidence=0.7)
    verdict = _make_verdict("P1", "E11.9", agrees=False)
    rules = _make_rules_result("P1", [])  # LOW

    decision = route(enrichment, verdict, rules)

    assert decision.routing_decision == "GOLD_REVIEW_CONFLICT"
    assert decision.review_flag is True
    assert decision.rules_risk == "LOW"
    assert decision.enricher_risk == "HIGH"


def test_route_gold_review_low_confidence():
    # Rules HIGH but enricher LOW (confidence < threshold) → low-confidence abstention
    enrichment = _make_enrichment("P1", "E11.9", confidence=0.3)
    verdict = _make_verdict("P1", "E11.9", agrees=True)
    rules = _make_rules_result("P1", ["medication_appropriateness"])  # HIGH via Cat 3

    decision = route(enrichment, verdict, rules)

    assert decision.routing_decision == "GOLD_REVIEW_LOW_CONFIDENCE"
    assert decision.review_flag is True
    assert decision.rules_risk == "HIGH"
    assert decision.enricher_risk == "LOW"


def test_confidence_threshold_boundary():
    # Exactly at threshold → enricher_risk HIGH
    enrichment = _make_enrichment("P1", "E11.9", confidence=CONFIDENCE_THRESHOLD)
    verdict = _make_verdict("P1", "E11.9", agrees=True)
    rules = _make_rules_result("P1", [])

    decision = route(enrichment, verdict, rules)
    assert decision.enricher_risk == "HIGH"
