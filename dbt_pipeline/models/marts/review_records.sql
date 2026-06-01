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
    routed_at
from {{ source('gold', 'gold_records') }}
where gold_status in ('enriched_review_conflict', 'enriched_review_low_confidence')
