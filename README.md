# AI-Enriched Clinical Risk Pipeline

[![CI](https://github.com/ericg1212/ai-healthcare-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/ericg1212/ai-healthcare-pipeline/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ericg1212/ai-healthcare-pipeline/actions/workflows/codeql.yml/badge.svg)](https://github.com/ericg1212/ai-healthcare-pipeline/actions/workflows/codeql.yml)
[![codecov](https://codecov.io/gh/ericg1212/ai-healthcare-pipeline/branch/main/graph/badge.svg)](https://codecov.io/gh/ericg1212/ai-healthcare-pipeline)
[![Release](https://img.shields.io/github/v/release/ericg1212/ai-healthcare-pipeline)](https://github.com/ericg1212/ai-healthcare-pipeline/releases)
[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)

[![Snowflake](https://img.shields.io/badge/Snowflake-29B5E8?logo=snowflake&logoColor=white)](https://www.snowflake.com/)
[![dbt](https://img.shields.io/badge/dbt-FF694B?logo=dbt&logoColor=white)](https://www.getdbt.com/)
[![Dagster](https://img.shields.io/badge/Dagster-4F43DD?logo=dagster&logoColor=white)](https://dagster.io/)
[![AWS S3](https://img.shields.io/badge/AWS_S3-232F3E?logo=amazonaws&logoColor=white)](https://aws.amazon.com/s3/)
[![FHIR R4](https://img.shields.io/badge/FHIR-R4-orange)](https://hl7.org/fhir/R4/)

Most healthcare AI pipelines treat enrichment as a black box — the model outputs a risk level, and that's the end of the audit trail. This pipeline makes the AI layer auditable: confidence scores flag uncertainty, a deterministic rules engine cross-validates every Claude output, and any disagreement or low-confidence record routes to a human review queue rather than downstream consumption. The result is a two-tier output — a **Gold layer** you can trust for automated action and a **Review layer** with an explainable reason for every flagged record.

**Key design principle:** Claude and the rules engine must agree for a record to pass to Gold. If they conflict, the record routes to Review automatically.

---

## What This Measures

| Question | Why it matters |
|---|---|
| Can AI enrichment reliably flag high-risk patients? | Proves Claude output is actionable, not just generative |
| Where do AI and deterministic rules agree vs. conflict? | Conflict cases surface the edge cases that require clinical judgment |
| What percentage of records auto-route to Gold vs. Review? | Quantifiable finding — the headline output of this pipeline |
| What drives review queue volume by category? | Tells you which clinical domain generates the most AI ambiguity |

---

## AI Layer

Four components run on every record, in sequence:

**1. Claude Enrichment**
Claude API assigns a risk level (High / Medium / Low), a plain-language clinical summary, and a confidence score (0.0–1.0). Confidence below 0.70 routes the record to Review without proceeding further.

**2. LLM-as-Judge**
A second Claude call receives the original record and the first enrichment output, then independently validates consistency. Disagreement between the two calls routes the record to Review.

**3. Structured Rules Engine (deterministic Python — 6 categories)**

| Category | Logic |
|---|---|
| Diabetes & Metabolic | HbA1c threshold flags |
| Cardiovascular | ER visit counts, risk flag patterns |
| Medication Safety | Medication gap detection |
| Care Gaps | Missing referrals, absent follow-ups |
| Data Completeness | Missing fields, invalid codes |
| Mental Health & Behavioral | Depression/anxiety (F32.x, F41.x) no referral → flag; opioid (F11.x) no MAT → high risk; psychiatric med no mental health ICD → flag; multiple psych meds no specialist → flag |

**4. Routing**
Any of the following sends a record to Review: confidence < 0.70, LLM-as-Judge disagreement, rules engine conflict with Claude output. Agreement on all three → Gold.

---

## Stack

| Layer | Technology |
|---|---|
| Synthetic data | Python FHIR R4 (Synthea) |
| Raw storage | AWS S3 |
| Warehouse | Snowflake |
| Orchestration | Dagster |
| AI enrichment | Claude API (Anthropic) |
| Transformation | dbt |
| Data quality | Great Expectations |
| Dashboard | Streamlit |
| CI | GitHub Actions |

---

## Architecture

```
Synthea (Python FHIR R4 generator)
         ↓
  Python FHIR Parser
         ↓
    AWS S3 (Raw FHIR JSON)
         ↓  COPY INTO
  Snowflake RAW layer
         ↓
  Dagster orchestration
         ↓
  dbt (Bronze → Silver staging)
         ↓
┌─────────────────────────────────┐
│        AI ENRICHMENT LAYER      │
│                                 │
│  1. Claude Enrichment           │
│     risk / summary / confidence │
│     confidence < 0.70 → REVIEW  │
│             ↓                   │
│  2. LLM-as-Judge                │
│     validates consistency       │
│     disagreement → REVIEW       │
│             ↓                   │
│  3. Structured Rules Engine     │
│     6 categories, deterministic │
│     conflict → REVIEW           │
│     agreement → GOLD            │
└─────────────────────────────────┘
         ↓
  Snowflake GOLD + REVIEW marts
         ↓
  dbt (mart layer)
         ↓
  Great Expectations (quality gates)
         ↓
  Streamlit dashboard
```

---

## Project Structure

```
ai-healthcare-pipeline/
├── data_ingestion/
│   ├── fhir_generator.py       # Synthea synthetic record generation
│   ├── fhir_parser.py          # Parse FHIR R4 JSON → structured dicts
│   └── load_to_snowflake.py    # S3 upload + Snowflake COPY INTO
├── ai_layer/
│   ├── enrichment.py           # Claude enrichment: risk, summary, confidence
│   ├── llm_judge.py            # LLM-as-Judge: validates enrichment output
│   └── rules_engine.py         # Structured Rules Engine: 6 categories
├── dbt_pipeline/
│   ├── models/
│   │   ├── staging/            # Bronze → Silver
│   │   └── marts/              # Gold + Review split
│   └── dbt_project.yml
├── dagster_pipelines/          # Orchestration assets and jobs
├── quality/                    # Great Expectations checkpoints
├── streamlit_app/              # Dashboard
└── tests/                      # pytest unit tests
```

---

## Future Enhancements

**[Priority 1] RAG with Clinical Guidelines**
Instead of Claude reasoning from training data alone, retrieve the current clinical guideline — ACC/AHA cardiovascular standards, ADA diabetes management, SAMHSA behavioral health protocols — and include it directly in the enrichment prompt. Claude then reasons against authoritative, current literature rather than potentially outdated training knowledge. Implementation requires a vector database (Pinecone) to store and retrieve guideline embeddings at inference time. Directly addresses the physician bypass question: records that pass Gold under RAG are grounded in named, dated, retrievable clinical evidence.

**SNOMED CT / RxNorm API Validation**
Clinical terminology verification against authoritative vocabularies at ingestion time.

**Confidence Threshold Calibration**
Tunable review queue sizing based on operational capacity and acceptable risk tolerance.

---

## Setup

```bash
git clone https://github.com/ericg1212/ai-healthcare-pipeline.git
cd ai-healthcare-pipeline
cp .env.example .env          # populate with your credentials
pip install -r requirements.txt
make test
```

See `.env.example` for required environment variables.

---

## Note on Synthetic Data

All patient records are generated by the Synthea synthetic patient engine. No real PHI is used, stored, or transmitted at any point in this pipeline.
