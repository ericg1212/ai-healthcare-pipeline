from __future__ import annotations
from typing import Union
from pydantic import BaseModel
from ai_layer.models import ConditionRecord, MedicationRecord


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
        if isinstance(record, ConditionRecord):
            return len(record.condition_code.replace(".", "").strip()) <= 3
        return False

    def _check_clinical_urgency(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        if isinstance(record, ConditionRecord):
            high_severity = {"I21", "I46", "J96", "N17", "G93"}
            prefix = record.condition_code[:3]
            return prefix in high_severity and record.onset_date is None
        return False

    def _check_coding_accuracy(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        if isinstance(record, ConditionRecord):
            invalid_prefixes = {"Z00", "Z01", "Z02"}
            prefix = record.condition_code[:3]
            return prefix in invalid_prefixes
        return False

    def _check_medication_appropriateness(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        if isinstance(record, MedicationRecord):
            unsupported_keywords = {"warfarin", "insulin", "methotrexate", "lithium"}
            med = record.medication_description.lower()
            return any(kw in med for kw in unsupported_keywords)
        return False

    def _check_drug_condition_alignment(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        if isinstance(record, MedicationRecord):
            return record.medication_code is None or record.medication_code.strip() == ""
        return False

    def _check_comorbidity_risk(self, record: Union[ConditionRecord, MedicationRecord]) -> bool:
        if isinstance(record, ConditionRecord):
            high_risk_prefixes = {"E11", "I25", "N18", "F32", "J44"}
            prefix = record.condition_code[:3]
            return prefix in high_risk_prefixes and record.onset_date is None
        return False
