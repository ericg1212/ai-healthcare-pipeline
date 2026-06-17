# Copyright (c) 2026 Eric Grynspan. All rights reserved.
from ai_layer.models import ConditionRecord
from ai_layer.terminology_validator import (
    _validate_snomed,
    validate_batch,
    log_validation_summary,
)


# ---------------------------------------------------------------------------
# SNOMED CT format validation (no network calls)
# ---------------------------------------------------------------------------

def test_snomed_valid_numeric_code():
    assert _validate_snomed("44054006") is True


def test_snomed_valid_long_code():
    assert _validate_snomed("709044004") is True


def test_snomed_rejects_non_numeric():
    assert _validate_snomed("E11.9") is False


def test_snomed_rejects_too_short():
    assert _validate_snomed("123") is False


def test_snomed_rejects_empty():
    assert _validate_snomed("") is False


def test_snomed_rejects_icd10_prefix():
    assert _validate_snomed("I21") is False


# ---------------------------------------------------------------------------
# validate_batch — no network, SNOMED format only (UMLS_API_KEY absent in CI)
# ---------------------------------------------------------------------------

def test_validate_batch_conditions():
    records = [
        ConditionRecord(patient_id="P1", condition_code="44054006",
                        condition_description="type 2 diabetes mellitus"),
        ConditionRecord(patient_id="P2", condition_code="E11",
                        condition_description="diabetes"),
    ]
    results = validate_batch(records)
    assert results[("P1", "44054006")] is True
    assert results[("P2", "E11")] is False


def test_validate_batch_returns_all_records():
    records = [
        ConditionRecord(patient_id="P1", condition_code="44054006",
                        condition_description="type 2 diabetes mellitus"),
        ConditionRecord(patient_id="P2", condition_code="709044004",
                        condition_description="chronic kidney disease stage 3"),
    ]
    results = validate_batch(records)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# log_validation_summary — output shape
# ---------------------------------------------------------------------------

def test_log_validation_summary_no_errors(capsys):
    results = {("P1", "44054006"): True, ("P2", "709044004"): True}
    log_validation_summary(results)
    out = capsys.readouterr().out
    assert "2/2 valid" in out
    assert "0 not found" in out


def test_log_validation_summary_with_invalid(capsys):
    results = {("P1", "44054006"): True, ("P2", "E11"): False}
    log_validation_summary(results)
    out = capsys.readouterr().out
    assert "1 not found" in out
    assert "E11" in out
