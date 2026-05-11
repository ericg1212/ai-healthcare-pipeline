import os
import boto3
import pandas as pd
import snowflake.connector
from pathlib import Path
from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas

from fhir_parser import parse_all

load_dotenv()

FHIR_DIR = Path(__file__).parent.parent / "synthetic_data" / "fhir"
S3_PREFIX = "raw/fhir/"

CREATE_STATEMENTS = {
    "PERSON": """
        CREATE TABLE IF NOT EXISTS RAW.PERSON (
            PATIENT_ID   VARCHAR,
            BIRTH_DATE   VARCHAR,
            GENDER       VARCHAR,
            STATE        VARCHAR,
            LOADED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """,
    "CONDITION": """
        CREATE TABLE IF NOT EXISTS RAW.CONDITION (
            PATIENT_ID   VARCHAR,
            CODE         VARCHAR,
            DESCRIPTION  VARCHAR,
            ONSET_DATE   VARCHAR,
            LOADED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """,
    "MEDICATION": """
        CREATE TABLE IF NOT EXISTS RAW.MEDICATION (
            PATIENT_ID   VARCHAR,
            CODE         VARCHAR,
            DESCRIPTION  VARCHAR,
            START_DATE   VARCHAR,
            LOADED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """,
    "ENCOUNTER": """
        CREATE TABLE IF NOT EXISTS RAW.ENCOUNTER (
            PATIENT_ID     VARCHAR,
            ENCOUNTER_ID   VARCHAR,
            ENCOUNTER_TYPE VARCHAR,
            START_DATE     VARCHAR,
            END_DATE       VARCHAR,
            LOADED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """,
}


def upload_to_s3(fhir_dir: Path) -> int:
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )
    bucket = os.getenv("S3_BUCKET_NAME")
    count = 0
    for path in sorted(fhir_dir.glob("*.json")):
        key = f"{S3_PREFIX}{path.name}"
        s3.upload_file(str(path), bucket, key)
        count += 1
    print(f"Uploaded {count} FHIR bundles to s3://{bucket}/{S3_PREFIX}")
    return count


def get_snowflake_conn():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database=os.getenv("SNOWFLAKE_DATABASE", "AI_HEALTHCARE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "RAW"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        role=os.getenv("SNOWFLAKE_ROLE"),
    )


def create_tables(conn):
    with conn.cursor() as cur:
        wh = os.getenv("SNOWFLAKE_WAREHOUSE", "AI_HEALTHCARE_WH")
        cur.execute("USE ROLE ACCOUNTADMIN")
        cur.execute(f"""
            CREATE WAREHOUSE IF NOT EXISTS {wh}
            WITH WAREHOUSE_SIZE = 'X-SMALL'
            AUTO_SUSPEND = 60
            AUTO_RESUME = TRUE
            INITIALLY_SUSPENDED = TRUE
        """)
        cur.execute(f"USE WAREHOUSE {wh}")
        cur.execute("CREATE DATABASE IF NOT EXISTS AI_HEALTHCARE")
        cur.execute("CREATE SCHEMA IF NOT EXISTS AI_HEALTHCARE.RAW")
        cur.execute("USE DATABASE AI_HEALTHCARE")
        cur.execute("USE SCHEMA RAW")
        for name, ddl in CREATE_STATEMENTS.items():
            cur.execute(ddl)
            print(f"Table RAW.{name} ready")


def load_table(conn, table: str, records: list) -> int:
    if not records:
        print(f"  No records for {table}, skipping")
        return 0
    df = pd.DataFrame(records)
    df.columns = [c.upper() for c in df.columns]
    success, _, nrows, _ = write_pandas(
        conn, df, table_name=table, schema="RAW", database="AI_HEALTHCARE"
    )
    if success:
        print(f"  Loaded {nrows} rows -> RAW.{table}")
    return nrows


def main():
    print("=== Step 1: Upload FHIR JSON to S3 ===")
    upload_to_s3(FHIR_DIR)

    print("\n=== Step 2: Parse FHIR bundles ===")
    data = parse_all(FHIR_DIR)
    for k, v in data.items():
        print(f"  {k}: {len(v)} records")

    print("\n=== Step 3: Load to Snowflake RAW ===")
    conn = get_snowflake_conn()
    try:
        create_tables(conn)
        load_table(conn, "PERSON", data["person"])
        load_table(conn, "CONDITION", data["conditions"])
        load_table(conn, "MEDICATION", data["medications"])
        load_table(conn, "ENCOUNTER", data["encounters"])
    finally:
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
