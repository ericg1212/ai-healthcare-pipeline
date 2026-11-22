import pytest

from ai_layer.judge_triggers import CATEGORIES, evaluate_triggers, semantic_tag, wilson_interval


def scores(**over):
    base = {c: 0.5 for c in CATEGORIES}
    base.update({"diagnosis_specificity": 0.6, "clinical_urgency": 0.3, "coding_accuracy": 0.7})
    base.update(over)
    return base


def test_t1_needs_generic_qualifier():
    # High score on a specific SNOMED disorder must NOT fire (v1 prompt fired on any score >= 0.85).
    r = evaluate_triggers(scores(coding_accuracy=0.9), 0.6, "44054006", "type 2 diabetes mellitus (disorder)")
    assert not r.t1_inflated
    # Same score on a generic description does fire.
    g = evaluate_triggers(scores(coding_accuracy=0.9), 0.6, "44054006", "diabetes (disorder)")
    assert g.t1_inflated


def test_t1_three_character_icd_code_is_generic():
    assert evaluate_triggers(scores(coding_accuracy=0.9), 0.6, "E11", "something specific (disorder)").t1_inflated


def test_t2_only_for_well_known_conditions_or_drugs():
    low = scores(clinical_urgency=0.2)
    assert evaluate_triggers(low, 0.5, "1", "essential hypertension (disorder)").t2_deflated
    assert not evaluate_triggers(low, 0.5, "1", "otitis media (disorder)").t2_deflated


def test_t3_condition_inconsistency_and_non_disorder_exemption():
    s = scores(coding_accuracy=0.9, diagnosis_specificity=0.2)
    assert evaluate_triggers(s, 0.5, "1", "chronic sinusitis (disorder)").t3_inconsistent
    for tag in ("finding", "situation", "person"):
        assert not evaluate_triggers(s, 0.5, "1", f"full-time employment ({tag})").t3_inconsistent


def test_t3_medication_inconsistency_not_exempt():
    s = scores(medication_appropriateness=0.9, drug_condition_alignment=0.2)
    assert evaluate_triggers(s, 0.5, "1", "metformin 500 mg oral tablet").t3_inconsistent


def test_t4_drift_boundary():
    s = {c: 0.5 for c in CATEGORIES}
    s["diagnosis_specificity"] = 0.3  # mean = 0.4667
    assert not evaluate_triggers(s, 0.66, "1", "x (disorder)").t4_drift  # diff 0.193
    assert evaluate_triggers(s, 0.70, "1", "x (disorder)").t4_drift  # diff 0.233


def test_t5_flat_scoring():
    flat = {c: 0.60 + 0.01 * i for i, c in enumerate(CATEGORIES)}  # spread 0.05
    assert evaluate_triggers(flat, 0.62, "1", "x (disorder)").t5_flat
    assert not evaluate_triggers(scores(), 0.5, "1", "x (disorder)").t5_flat


def test_disagrees_lists_fired_triggers():
    r = evaluate_triggers(scores(coding_accuracy=0.9, diagnosis_specificity=0.2), 0.5, "1", "pain (disorder)")
    assert r.disagrees and r.fired == ["T1", "T3"]


def test_semantic_tag():
    assert semantic_tag("Cough (Finding)") == "finding"
    assert semantic_tag("no tag here") is None


def test_wilson_interval_known_values():
    lo, hi = wilson_interval(13, 166)
    assert round(lo, 3) == 0.046 and round(hi, 3) == 0.129
    lo0, hi0 = wilson_interval(0, 166)
    assert lo0 == pytest.approx(0.0, abs=1e-12) and 0.02 < hi0 < 0.03
    with pytest.raises(ValueError):
        wilson_interval(1, 0)
