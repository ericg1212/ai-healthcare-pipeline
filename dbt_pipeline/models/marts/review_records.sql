-- Copyright (c) 2026 Eric Grynspan. All rights reserved.
{{ config(materialized='table') }}

select
    patient_id,
    record_type,
    record_code,
    record_description,
    overall_confidence,
    gold_status,
    review_reason,
    flags_triggered,
    judge_agrees,
    corrected_confidence,
    diagnosis_specificity_rationale,
    clinical_urgency_rationale,
    coding_accuracy_rationale,
    medication_appropriateness_rationale,
    drug_condition_alignment_rationale,
    comorbidity_risk_rationale,
    run_id,
    routed_at
from {{ source('gold', 'gold_records') }}
where gold_status in ('enriched_review_conflict', 'enriched_review_low_confidence')
