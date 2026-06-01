{{ config(materialized='table') }}

-- Gold layer: final routed risk scores per patient record.
-- Source: GOLD_ROUTING_STAGE written by gold_routing Dagster asset.

with source as (
    select * from {{ source('gold_stage', 'routing_results') }}
),

final as (
    select
        patient_id,
        record_code,
        record_type,
        rules_risk,
        enricher_confidence,
        enricher_risk,
        judge_agrees,
        corrected_confidence,
        routing_decision,
        review_flag,
        routing_reason,
        cost_usd,
        processed_at,
        case
            when routing_decision = 'GOLD_CLEAN' and rules_risk = 'HIGH' then 'HIGH_RISK'
            when routing_decision = 'GOLD_CLEAN' and rules_risk = 'LOW'  then 'LOW_RISK'
            else 'REVIEW_QUEUE'
        end as risk_category
    from source
)

select * from final
