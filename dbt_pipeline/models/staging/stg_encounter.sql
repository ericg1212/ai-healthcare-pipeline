WITH source AS (
      SELECT * FROM {{ source('raw', 'encounter') }}
  ),
  renamed AS (
      SELECT
          PATIENT_ID                      AS patient_id,
          ENCOUNTER_ID                    AS encounter_id,
          LOWER(ENCOUNTER_TYPE)           AS encounter_type,
          TRY_CAST(START_DATE AS DATE)    AS start_date,
          TRY_CAST(END_DATE AS DATE)      AS end_date,
          LOADED_AT                       AS loaded_at
      FROM source
      QUALIFY ROW_NUMBER() OVER (PARTITION BY ENCOUNTER_ID ORDER BY
  LOADED_AT DESC) = 1
  )
  SELECT * FROM renamed