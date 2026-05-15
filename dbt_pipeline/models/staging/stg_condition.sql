WITH source AS (
      SELECT * FROM {{ source('raw', 'condition') }}
  ),
  renamed AS (
      SELECT
          PATIENT_ID                      AS patient_id,
          CODE                            AS condition_code,
          LOWER(DESCRIPTION)              AS condition_description,
          TRY_CAST(ONSET_DATE AS DATE)    AS onset_date,
          LOADED_AT                       AS loaded_at
      FROM source
      QUALIFY ROW_NUMBER() OVER (PARTITION BY PATIENT_ID, CODE ORDER BY
  LOADED_AT DESC) = 1
  )
  SELECT * FROM renamed