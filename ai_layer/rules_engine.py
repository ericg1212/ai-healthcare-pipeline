# Copyright (c) 2026 Eric Grynspan. All rights reserved.
from __future__ import annotations
from typing import Union
from pydantic import BaseModel
from ai_layer.models import ConditionRecord, MedicationRecord

# SNOMED CT uses numeric concept IDs — ICD-10 prefix matching never fires on this data.
# All condition rules use description-based matching on the normalized lowercase text
# produced by stg_condition (LOWER(DESCRIPTION)).

_ACUTE_TERMS = frozenset({
    "myocardial infarction", "cardiac arrest", "respiratory failure",
    "acute kidney failure", "sepsis", "cerebral infarction",
    "acute heart failure", "anaphylaxis", "diabetic ketoacidosis",
})

_HIGH_RISK_CHRONIC = frozenset({
    "type 2 diabetes", "chronic kidney disease", "ischemic heart disease",
    "coronary artery disease", "major depression", "depressive disorder",
    "chronic obstructive pulmonary", "heart failure",
})

_VAGUE_DESCRIPTIONS = frozenset({
    "finding", "disorder", "condition", "observation", "situation",
    "abnormal", "problem", "complaint",
})

# ISMP high-alert medications — valid clinically, but require review for appropriateness.
_HIGH_RISK_MEDS = frozenset({
    "warfarin", "insulin", "methotrexate", "lithium",
})


class RulesEngineResult(BaseModel):
    patient_id: str
    diagnosis_specificity_flag: bool
    clinical_urgency_flag: bool
    coding_accuracy_flag: bool
    medication_appropriateness_flag: bool
    drug_condition_alignment_flag: bool
    comorbidity_risk_flag: bool
    flags_triggered: list[str]


class RulesEngine:

    def evaluate(self, record: Union[ConditionRecord, MedicationRecord]) -> RulesEngineResult:
        flags = {}
        flags["diagnosis_specificity"] = self._check_diagnosis_specificity(record)
        flags["clinical_urgency"] = self._check_clinical_urgency(record)
        flags["coding_accuracy"] = self._check_coding_accuracy(record)
        flags["medication_appropriateness"] = self._check_medication_appropriateness(record)
        flags["drug_condition_alignment"] = self._check_drug_condition_alignment(record)
        flags["comorbidity_risk"] = self._check_comorbidity_risk(record)

        triggered = [k for k, v in flags.items() if v]

        return RulesEngineResult(
            patient_id=record.patient_id,
            diagnosis_specificity_flag=flags["diagnosis_specificity"],
            clinical_urgency_flag=flags["clinical_urgency"],
            coding_accuracy_flag=flags["coding_accuracy"],
            medication_appropriateness_flag=flags["medication_appropriateness"],
            drug_condition_alignment_flag=flags["drug_condition_alignment"],
            comorbidity_risk_flag=flags["comorbidity_risk"],
            flags_triggered=triggered,
        )

    def _check_diagnosis_specificity(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        """Flag SNOMED CT conditions with vague or single-word descriptions (low concept specificity)."""
        if isinstance(record, ConditionRecord):
            desc = record.condition_description.lower().strip()
            return len(desc.split()) <= 1 or desc in _VAGUE_DESCRIPTIONS
        return False

    def _check_clinical_urgency(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        """Flag acute high-severity conditions missing an onset_date (data completeness gap)."""
        if isinstance(record, ConditionRecord):
            desc = record.condition_description.lower()
            is_acute = any(term in desc for term in _ACUTE_TERMS)
            return is_acute and record.onset_date is None
        return False

    def _check_coding_accuracy(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        """Flag conditions where the description is empty or a known non-specific placeholder."""
        if isinstance(record, ConditionRecord):
            desc = record.condition_description.lower().strip()
            return not desc or desc in _VAGUE_DESCRIPTIONS
        return False

    def _check_medication_appropriateness(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        """Flag ISMP high-alert medications — clinically valid but require explicit review."""
        if isinstance(record, MedicationRecord):
            med = record.medication_description.lower()
            return any(kw in med for kw in _HIGH_RISK_MEDS)
        return False

    def _check_drug_condition_alignment(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        """Flag medication records with a missing or blank RxNorm code."""
        if isinstance(record, MedicationRecord):
            return not record.medication_code or not record.medication_code.strip()
        return False

    def _check_comorbidity_risk(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        """Flag high-risk chronic conditions missing an onset_date (required for RWE cohort dating)."""
        if isinstance(record, ConditionRecord):
            desc = record.condition_description.lower()
            is_high_risk = any(term in desc for term in _HIGH_RISK_CHRONIC)
            return is_high_risk and record.onset_date is None
        return False
