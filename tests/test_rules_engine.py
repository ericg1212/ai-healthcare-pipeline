from datetime import date
from ai_layer.models import ConditionRecord, MedicationRecord
from ai_layer.rules_engine import RulesEngine

engine = RulesEngine()


def test_diagnosis_specificity_flags_single_word_description():
    r = ConditionRecord(patient_id="P001", condition_code="44054006", condition_description="finding")
    result = engine.evaluate(r)
    assert result.diagnosis_specificity_flag is True
    assert "diagnosis_specificity" in result.flags_triggered


def test_diagnosis_specificity_clean_on_specific_description():
    r = ConditionRecord(
        patient_id="P001",
        condition_code="44054006",
        condition_description="type 2 diabetes mellitus",
        onset_date=date(2020, 1, 1),
    )
    result = engine.evaluate(r)
    assert result.diagnosis_specificity_flag is False


def test_clinical_urgency_flags_acute_without_onset():
    r = ConditionRecord(patient_id="P002", condition_code="57054005", condition_description="myocardial infarction")
    result = engine.evaluate(r)
    assert result.clinical_urgency_flag is True
    assert "clinical_urgency" in result.flags_triggered


def test_clinical_urgency_clean_when_onset_present():
    r = ConditionRecord(
        patient_id="P002",
        condition_code="57054005",
        condition_description="myocardial infarction",
        onset_date=date(2023, 6, 1),
    )
    result = engine.evaluate(r)
    assert result.clinical_urgency_flag is False


def test_coding_accuracy_flags_empty_description():
    r = ConditionRecord(patient_id="P003", condition_code="44054006", condition_description="  ")
    result = engine.evaluate(r)
    assert result.coding_accuracy_flag is True


def test_coding_accuracy_flags_vague_placeholder():
    r = ConditionRecord(patient_id="P003", condition_code="44054006", condition_description="disorder")
    result = engine.evaluate(r)
    assert result.coding_accuracy_flag is True


def test_medication_appropriateness_flags_high_risk_med():
    r = MedicationRecord(patient_id="P004", medication_code="855332", medication_description="warfarin 5mg oral tablet")
    result = engine.evaluate(r)
    assert result.medication_appropriateness_flag is True
    assert "medication_appropriateness" in result.flags_triggered


def test_medication_appropriateness_clean_on_standard_med():
    r = MedicationRecord(
        patient_id="P004", medication_code="860975",
        medication_description="metformin 500 mg oral tablet",
    )
    result = engine.evaluate(r)
    assert result.medication_appropriateness_flag is False


def test_drug_condition_alignment_flags_missing_rxnorm():
    r = MedicationRecord(patient_id="P005", medication_code="", medication_description="metformin 500mg")
    result = engine.evaluate(r)
    assert result.drug_condition_alignment_flag is True


def test_comorbidity_risk_flags_chronic_without_onset():
    r = ConditionRecord(
        patient_id="P006", condition_code="709044004",
        condition_description="chronic kidney disease stage 3",
    )
    result = engine.evaluate(r)
    assert result.comorbidity_risk_flag is True
    assert "comorbidity_risk" in result.flags_triggered


def test_comorbidity_risk_clean_when_onset_present():
    r = ConditionRecord(
        patient_id="P006",
        condition_code="709044004",
        condition_description="chronic kidney disease stage 3",
        onset_date=date(2019, 3, 15),
    )
    result = engine.evaluate(r)
    assert result.comorbidity_risk_flag is False


def test_clean_record_no_flags():
    r = ConditionRecord(
        patient_id="P007",
        condition_code="44054006",
        condition_description="type 2 diabetes mellitus without complications",
        onset_date=date(2021, 5, 10),
    )
    result = engine.evaluate(r)
    assert result.flags_triggered == []
