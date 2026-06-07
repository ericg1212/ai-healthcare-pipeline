{{ config(materialized='table') }}

select
    patient_id,
    record_type,
    record_code,
    record_description,
    overall_confidence,
    flags_triggered,
    judge_agrees,
    corrected_confidence,
    review_reason,
    diagnosis_specificity_rationale,
    clinical_urgency_rationale,
    coding_accuracy_rationale,
    medication_appropriateness_rationale,
    drug_condition_alignment_rationale,
    comorbidity_risk_rationale,
    routed_at
from {{ source('gold', 'gold_records') }}
where gold_status = 'enriched_clean'
