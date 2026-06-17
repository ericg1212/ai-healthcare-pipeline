-- Copyright (c) 2026 Eric Grynspan. All rights reserved.
WITH source AS (
      SELECT * FROM {{ source('raw', 'medication') }}
  ),
  renamed AS (
      SELECT
          PATIENT_ID                      AS patient_id,
          CODE                            AS medication_code,
          LOWER(DESCRIPTION)              AS medication_description,
          TRY_CAST(START_DATE AS DATE)    AS start_date,
          LOADED_AT                       AS loaded_at
      FROM source
      QUALIFY ROW_NUMBER() OVER (PARTITION BY PATIENT_ID, CODE ORDER BY
  LOADED_AT DESC) = 1
  )
  SELECT * FROM renamed