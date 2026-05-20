from datetime import date
from ai_layer.models import ConditionRecord, MedicationRecord
from ai_layer.rules_engine import RulesEngine

engine = RulesEngine()

# Should flag diagnosis_specificity (3-char ICD)
r1 = ConditionRecord(patient_id="P001", condition_code="E11", condition_description="Type 2 diabetes")
print(engine.evaluate(r1))

# Should flag medication_appropriateness (warfarin, no supporting ICD)
r2 = MedicationRecord(patient_id="P002", medication_code="855332", medication_description="warfarin 5mg")
print(engine.evaluate(r2))

# Should flag nothing (specific ICD, normal med)
r3 = ConditionRecord(
    patient_id="P003", condition_code="E11.9",
    condition_description="T2D no complications", onset_date=date(2022, 1, 1)
)
print(engine.evaluate(r3))
