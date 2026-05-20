# AI Clinical Documentation Intelligence Pipeline

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

Clinical documentation gaps are the leading driver of prior authorization denials and downstream revenue loss — yet most AI enrichment pipelines produce a risk score with no audit trail. This pipeline builds the governance layer that's missing: every Claude output is cross-validated by a deterministic rules engine, confidence scores flag uncertainty before it reaches production, and any conflict routes to a human review queue with an explainable reason. The result is a two-tier output — a **Gold layer** you can trust for automated action and a **Review layer** with a traceable reason for every flagged record.

**Key design principle:** Claude and the rules engine must agree for a record to pass to Gold. Conflict or low confidence → Review, automatically, with a reason.

---

## Scale

| Metric | Value |
|---|---|
| Patient records | 226 synthetic FHIR R4 patients |
| Total clinical records | 25,958 (conditions + medications + encounters) |
| AI enrichment categories | 6 per record |
| Confidence threshold | 0.70 (configurable) |
| Rules engine categories | 6 deterministic clinical domains |
| Validation gate | Dual — LLM-as-Judge + Rules Engine |

---

## What This Measures

| Question | Why it matters |
|---|---|
| Can AI enrichment reliably flag high-risk patients? | Proves Claude output is actionable, not just generative |
| Where do AI and deterministic rules agree vs. conflict? | Conflict cases surface edge cases requiring clinical judgment |
| What percentage of records auto-route to Gold vs. Review? | Quantifiable finding — the headline output of this pipeline |
| What drives review queue volume by category? | Identifies which clinical domain generates the most AI ambiguity |

---

## AI Layer

Four components run on every record. Components 1 and 2 are live; 3 and 4 are Phase 2.

**1. Claude Enrichment** ✓ Live

Each condition and medication record is scored across 6 clinical quality dimensions. Claude is called via `tool_use` — structured output only, no free-text parsing. The system prompt (~2,000 tokens) is prompt-cached, so calls 2–N in a batch cost ~10% of the first call's input token price.

| Category | What It Measures |
|---|---|
| `diagnosis_specificity` | ICD-10 code specificity — 7-char codes score high, 3-char catch-alls score low |
| `clinical_urgency` | Implied acuity — acute/life-threatening vs. stable chronic vs. preventive |
| `coding_accuracy` | Description-to-code alignment — catches mismatches between free text and coded values |
| `medication_appropriateness` | Whether the medication is clinically reasonable given the record context |
| `drug_condition_alignment` | Recognized drug-condition pairing — metformin + T2D, lisinopril + hypertension, etc. |
| `comorbidity_risk` | Multi-condition risk signal — T2D + CKD, metabolic syndrome clusters |

Each category returns a score (0.0–1.0) and a one-sentence rationale citing the specific code or clinical pattern. `overall_confidence` is a weighted average: `diagnosis_specificity` and `coding_accuracy` at 1.5×, all others at 1×. A Pydantic `model_validator` enforces that `overall_confidence` cannot diverge more than 0.25 from the category average — invalid enrichments raise at parse time, not silently downstream.

**2. LLM-as-Judge** ✓ Live

A second Claude call audits the enrichment result. The judge receives scores only — rationale is hidden to prevent anchoring bias. Five disagreement triggers are defined:

1. **Inflated score** — category ≥ 0.85 on a Synthea record with a 3-char ICD-10 code or generic description
2. **Deflated score** — category ≤ 0.25 on a well-known chronic condition or textbook first-line medication
3. **Internal inconsistency** — `coding_accuracy ≥ 0.8` with `diagnosis_specificity ≤ 0.4`, or `medication_appropriateness ≥ 0.85` with `drug_condition_alignment ≤ 0.3`
4. **Overall drift** — `overall_confidence` diverges more than 0.20 from the simple category average
5. **Flat scoring** — all 6 scores within 0.05 of each other (enricher was not discriminating)

When the judge disagrees, it returns `corrected_confidence`, the specific `disagreement_categories`, and a one-sentence clinical reason. Both Claude calls use prompt caching on their respective system prompts.

**3. Structured Rules Engine** — Phase 2

Deterministic Python — 6 categories (Diabetes & Metabolic, Cardiovascular, Medication Safety, Care Gaps, Data Completeness, Mental Health & Behavioral). Runs parallel to Claude on every record. Flag aggregation rule: HIGH if `flags_fired ≥ 2` OR any Medication Safety flag fires.

**4. Gold / Review Routing** — Phase 2

LLM-as-Judge disagreement or rules engine conflict → Review queue with explainable reason. Full agreement → Gold layer. Three Gold record states: enriched clean, enriched + review_flag (genuine conflict), enriched + review_flag (low confidence abstention).

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
│     6-category scoring          │
│     confidence < 0.70 → REVIEW  │
│             ↓                   │
│  2. LLM-as-Judge                │
│     blind audit, 5 triggers     │
│     disagreement → REVIEW       │
│             ↓                   │
│  3. Structured Rules Engine     │
│     6 clinical categories       │
│     deterministic cross-check   │
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
│   ├── fhir_generator.py       # Synthea JAR wrapper — 226 FHIR R4 patient bundles
│   ├── fhir_parser.py          # Parse FHIR R4 JSON → PERSON/CONDITION/MEDICATION/ENCOUNTER
│   └── load_to_snowflake.py    # S3 upload + Snowflake COPY INTO (25,958 records)
├── ai_layer/
│   ├── models.py               # Pydantic schemas: ConditionRecord, MedicationRecord,
│   │                           #   EnrichmentResult (6 CategoryScore fields + validator),
│   │                           #   JudgeVerdict (5 triggers + corrected_confidence)
│   ├── enricher.py             # Claude enrichment — tool_use structured output,
│   │                           #   prompt caching, 6-category scoring, enrich_batch()
│   ├── judge.py                # LLM-as-Judge — blind review, 5 disagreement triggers,
│   │                           #   corrected_confidence, judge_batch()
│   ├── rules_engine.py         # Deterministic rules — 6 clinical categories, binary flags
│   └── run_enrichment.py       # CLI entry: Snowflake staging → enrich → judge → JSON
│                               #   usage: python -m ai_layer.run_enrichment --limit 10
├── dbt_pipeline/
│   ├── models/
│   │   ├── staging/            # stg_person, stg_condition, stg_medication, stg_encounter
│   │   └── marts/              # Gold + Review split (Phase 2)
│   └── dbt_project.yml
├── dagster_pipelines/
│   ├── assets.py               # 6 SDAs: fhir_s3_upload → snowflake_raw_tables →
│   │                           #   dbt_staging_models → condition_enrichments +
│   │                           #   medication_enrichments → ai_enrichment_verdicts
│   └── definitions.py          # Dagster Definitions entry point
├── workspace.yaml              # dagster dev -m dagster_pipelines
├── quality/                    # Great Expectations checkpoints
├── streamlit_app/              # Dashboard (Phase 2)
└── tests/                      # pytest unit tests
```

---

## Portfolio Arc

| Project | Focus | Status |
|---|---|---|
| [Healthcare Claims Intelligence Pipeline](https://github.com/ericg1212/healthcare-claims-pipeline) | RCM retrospective — classify 257K denied claims by root cause | Complete |
| **AI Clinical Documentation Intelligence Pipeline** | AI governance — enrich + cross-validate + route clinical records | Active |
| P4 (planned) | Real-time denial prevention — streaming ingestion, rules-based scoring at submission | Planned |

---

## Future Enhancements

**[Priority 1] RAG with Clinical Guidelines**
Instead of Claude reasoning from training data alone, retrieve the current clinical guideline — ACC/AHA cardiovascular standards, ADA diabetes management, SAMHSA behavioral health protocols — and include it directly in the enrichment prompt. Claude then reasons against authoritative, current literature rather than potentially outdated training knowledge. Implementation requires a vector database (Pinecone) to store and retrieve guideline embeddings at inference time.

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
