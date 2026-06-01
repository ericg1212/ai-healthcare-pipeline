{{ config(materialized='table') }}

select
    patient_id,
    record_type,
    record_code,
    record_description,
    overall_confidence,
    judge_agrees,
    corrected_confidence,
    routed_at
from {{ source('gold', 'gold_records') }}
where gold_status = 'enriched_clean'
