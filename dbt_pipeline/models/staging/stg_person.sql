-- Copyright (c) 2026 Eric Grynspan. All rights reserved.
WITH source AS (
    SELECT * FROM {{ source('raw', 'person') }}
),
renamed AS (
      SELECT
          PATIENT_ID        AS person_id,
          TRY_CAST(BIRTH_DATE AS DATE)  AS birth_date,
          LOWER(GENDER)     AS gender,
          STATE             AS state,
          LOADED_AT         AS loaded_at
      FROM source
      QUALIFY ROW_NUMBER() OVER (PARTITION BY PATIENT_ID ORDER BY LOADED_AT
  DESC) = 1
  )
  SELECT * FROM renamed