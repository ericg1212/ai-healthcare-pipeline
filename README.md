# Trust but Verify: Clinical AI Governance Engine

[![CI](https://github.com/ericg1212/ai-healthcare-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/ericg1212/ai-healthcare-pipeline/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ericg1212/ai-healthcare-pipeline/actions/workflows/codeql.yml/badge.svg)](https://github.com/ericg1212/ai-healthcare-pipeline/actions/workflows/codeql.yml)
[![codecov](https://codecov.io/gh/ericg1212/ai-healthcare-pipeline/branch/main/graph/badge.svg)](https://codecov.io/gh/ericg1212/ai-healthcare-pipeline)
[![Release](https://img.shields.io/github/v/release/ericg1212/ai-healthcare-pipeline)](https://github.com/ericg1212/ai-healthcare-pipeline/releases)
[![dbt Docs](https://img.shields.io/badge/dbt%20Docs-live-FF694B?style=flat-square&logo=dbt&logoColor=white)](https://ericg1212.github.io/ai-healthcare-pipeline/)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Snowflake](https://img.shields.io/badge/Snowflake-29B5E8?style=flat-square&logo=snowflake&logoColor=white)](https://www.snowflake.com/)
[![dbt](https://img.shields.io/badge/dbt-FF694B?style=flat-square&logo=dbt&logoColor=white)](https://www.getdbt.com/)
[![Dagster](https://img.shields.io/badge/Dagster-4F43DD?style=flat-square&logo=dagster&logoColor=white)](https://dagster.io/)
[![AWS S3](https://img.shields.io/badge/AWS%20S3-232F3E?style=flat-square&logo=amazonaws&logoColor=white)](https://aws.amazon.com/s3/)
[![FHIR R4](https://img.shields.io/badge/HL7%20FHIR-R4-E8670A?style=flat-square)](https://hl7.org/fhir/R4/)

![Patients](https://img.shields.io/badge/Patients-226-0ea5e9?style=flat-square)
![Records](https://img.shields.io/badge/Clinical%20Records-25%2C958-8b5cf6?style=flat-square)
![Categories](https://img.shields.io/badge/Enrichment%20Categories-6-22c55e?style=flat-square)
![Rules Domains](https://img.shields.io/badge/Rules%20Engine%20Domains-6-f59e0b?style=flat-square)

**By [Eric Grynspan](https://www.linkedin.com/in/ericgrynspan/)** &nbsp;·&nbsp; [Portfolio](https://ericg1212.github.io) &nbsp;·&nbsp; [← P2 — Denied](https://github.com/ericg1212/healthcare-claims-pipeline)

---

## Portfolio Arc

P2 classified denials retrospectively. P3 adds AI governance. P4 prevents the denial before it happens.

| Project | Focus | Status |
|---|---|---|
| [P2 — Denied](https://github.com/ericg1212/healthcare-claims-pipeline) | Retrospective denial classification — separate 27K systematic denials with an upstream fix from 229K documentation failures requiring a different intervention | Live |
| **[P3 — Trust but Verify *(this project)*](https://github.com/ericg1212/ai-healthcare-pipeline)** | Clinical AI governance — LLM enrichment + rules engine cross-validation, every routing decision explainable | Live |
| P4 — Cleared *(planned)* | Real-time prior auth prevention — RAG-enhanced payer criteria matching at point of submission, streaming ingestion | Planned |

---

Clinical documentation gaps are the leading driver of prior authorization denials and downstream revenue loss — a problem that CMS-0057-F now mandates health systems address with real-time decision transparency. Yet most AI enrichment pipelines produce a risk score with no audit trail. This pipeline builds the governance layer that's missing: every LLM output is cross-validated by a deterministic rules engine, confidence scores flag uncertainty before it reaches production, and any conflict routes to a human review queue with an explainable reason. The result is a two-tier output — a **Gold layer** you can trust for automated action and a **Review layer** with a traceable reason for every flagged record.

**Trust but verify:** The LLM and the rules engine must agree for a record to pass to Gold. Conflict or low confidence → Review, automatically, with a reason.

---

## Why Dual Validation?

A single LLM confidence score is insufficient for clinical governance — it only tells you how certain the model is about its own output. It cannot tell you whether that output violates a domain rule a generalist model might not reliably enforce.

This pipeline uses two orthogonal validators targeting different failure modes:

| Validator | Failure Mode It Catches |
|---|---|
| **LLM-as-Judge** | Statistical inconsistencies *within* the AI output — inflated scores, flat scoring, internal contradictions between categories |
| **Rules Engine** | Domain violations the LLM might miss — Medication Safety flags, care gaps, missing diagnoses in high-risk comorbidity clusters |

Trust the model's enrichment output as a starting signal — verify it independently against a deterministic standard before it acts. A record that passes one validator but not the other still routes to Review. Both must agree for Gold. This design survives the failure mode where a confident but wrong LLM output would otherwise pass a threshold gate unchallenged.

---

## AI Layer

Four components run on every record. Components 1, 2, and 3 are live; 4 is Phase 2.

**1. LLM Enrichment** ✓ Live

Each condition and medication record is scored across 6 clinical quality dimensions. The LLM is called via `tool_use` — structured output only, no free-text parsing. The system prompt (~2,000 tokens) is prompt-cached, so calls 2–N in a batch cost ~10% of the first call's input token price.

| Category | What It Measures |
|---|---|
| `diagnosis_specificity` | SNOMED CT / RxNorm concept specificity — leaf-level concepts score high, broad category codes score low |
| `clinical_urgency` | Implied acuity — acute/life-threatening vs. stable chronic vs. preventive |
| `coding_accuracy` | Description-to-code alignment — catches mismatches between free text and coded values |
| `medication_appropriateness` | Whether the medication is clinically reasonable given the record context |
| `drug_condition_alignment` | Recognized drug-condition pairing — metformin + T2D, lisinopril + hypertension, etc. |
| `comorbidity_risk` | Multi-condition risk signal — T2D + CKD, metabolic syndrome clusters |

Each category returns a score (0.0–1.0) and a one-sentence rationale citing the specific code or clinical pattern. `overall_confidence` is a weighted average: `diagnosis_specificity` and `coding_accuracy` at 1.5×, all others at 1×. A Pydantic `model_validator` enforces that `overall_confidence` cannot diverge more than 0.25 from the category average — invalid enrichments raise at parse time, not silently downstream.

**2. LLM-as-Judge** ✓ Live

A second LLM call audits the enrichment result. The judge receives scores only — rationale is hidden to prevent anchoring bias. Five disagreement triggers are defined:

1. **Inflated score** — category ≥ 0.85 on a Synthea record with a broad-category SNOMED concept or generic description
2. **Deflated score** — category ≤ 0.25 on a well-known chronic condition or textbook first-line medication
3. **Internal inconsistency** — `coding_accuracy ≥ 0.8` with `diagnosis_specificity ≤ 0.4`, or `medication_appropriateness ≥ 0.85` with `drug_condition_alignment ≤ 0.3`
4. **Overall drift** — `overall_confidence` diverges more than 0.20 from the simple category average
5. **Flat scoring** — all 6 scores within 0.05 of each other (enricher was not discriminating)

When the judge disagrees, it returns `corrected_confidence`, the specific `disagreement_categories`, and a one-sentence clinical reason. Both LLM calls use prompt caching on their respective system prompts.

**3. Structured Rules Engine** ✓ Live

Deterministic Python — 6 categories (Diabetes & Metabolic, Cardiovascular, Medication Safety, Care Gaps, Data Completeness, Mental Health & Behavioral). Runs parallel to the LLM on every record. Flag aggregation rule: HIGH if `flags_fired ≥ 2` OR any Medication Safety flag fires.

**4. Gold / Review Routing** ✓ Live

LLM-as-Judge disagreement or rules engine conflict → Review queue with explainable reason. Full agreement → Gold layer. Three Gold record states: `enriched_clean` (trusted for downstream analytics), `enriched_review_conflict` (judge disagrees or rules fired), `enriched_review_low_confidence` (both agree but confidence < 0.55). Each Review record carries a `review_reason` string — a human-readable explanation of exactly why it was flagged.

---

## Design Decisions

**Why `tool_use` instead of free-text parsing?**
Structured output enforced at the API level — the LLM cannot return malformed JSON or skip a required field. Pydantic validates on ingestion; invalid enrichments raise at parse time, not silently downstream. This eliminates an entire class of data quality bugs.

**Why prompt caching?**
The system prompt is ~2,000 tokens and identical across every record in a batch. Caching it means calls 2–N cost ~10% of the first call's input token price. At batch scale this is a 5–10× cost reduction with zero quality tradeoff.

**Why a `model_validator` on `overall_confidence`?**
Allowing `overall_confidence` to diverge arbitrarily from the category average creates a silent inconsistency — a record could show HIGH overall confidence with LOW individual scores. The validator enforces ≤0.25 divergence at parse time, making the enrichment self-consistent by construction.

**Why rationale hidden from the Judge?**
Anchoring bias: if the Judge sees the enricher's reasoning, it tends to rationalize rather than audit. Scores-only input forces the Judge to evaluate statistical consistency independently, which is the only thing it can do objectively.

**Why deterministic rules alongside the LLM?**
LLMs are probabilistic — the same record can score differently across runs. For Medication Safety and high-risk comorbidity flags (T2D + CKD, polypharmacy), deterministic enforcement is non-negotiable. The rules engine provides a stable, auditable floor that doesn't drift.

---

## Results

| Metric | Value |
|---|---|
| Enrichment success rate | 97/100 records scored without validation errors (3 errors) |
| Avg overall_confidence | 0.584 across conditions + medications |
| Confidence threshold | 0.55 — records below routed to `enriched_review_low_confidence` |
| Most common Judge trigger | Internal inconsistency (coding_accuracy vs. diagnosis_specificity) |
| Prompt cache hit rate | ~90%+ on batches > 10 records |
| Pydantic validation failures | Raised at parse time — zero silent failures downstream |
| Gold routing states | `enriched_clean` / `enriched_review_conflict` / `enriched_review_low_confidence` |

---

## Scale

| Metric | Value |
|---|---|
| Patient records | 226 synthetic FHIR R4 patients |
| Total clinical records | 25,958 (conditions + medications + encounters) |
| AI enrichment categories | 6 per record |
| Confidence threshold | 0.55 (configurable via `router.py`) |
| Rules engine categories | 6 deterministic clinical domains |
| Validation gate | Dual — LLM-as-Judge + Rules Engine |

---

## Stack

| Layer | Technology |
|---|---|
| Synthetic data | Python FHIR R4 (Synthea) |
| Raw storage | AWS S3 |
| Warehouse | Snowflake |
| Transformation | dbt |
| AI enrichment | Anthropic API |
| Orchestration | Dagster |
| Dashboard | Streamlit *(Phase 2)* |
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
  dbt (Bronze → Silver staging)
         ↓
┌─────────────────────────────────┐
│        AI ENRICHMENT LAYER      │
│                                 │
│  1. LLM Enrichment              │
│     6-category scoring          │
│     confidence < 0.55 → REVIEW  │
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
  Dagster (orchestrates full asset graph)
         ↓
  Streamlit dashboard (Phase 2)
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
│   │                           #   EnrichmentResult, JudgeVerdict, GoldRecord
│   ├── enricher.py             # LLM enrichment — SNOMED CT/RxNorm aware, tool_use
│   │                           #   structured output, prompt caching, patient context
│   │                           #   injection, concurrent enrich_batch()
│   ├── judge.py                # LLM-as-Judge — blind review, 5 disagreement triggers,
│   │                           #   corrected_confidence, concurrent judge_batch()
│   ├── rules_engine.py         # Deterministic rules — 6 clinical categories, binary flags
│   ├── router.py               # Gold/Review routing gate — 3 gold states, conflict
│   │                           #   detection, confidence threshold (0.55)
│   └── run_enrichment.py       # CLI + Snowflake loaders incl. load_patient_context()
├── dbt_pipeline/
│   ├── models/
│   │   ├── staging/            # stg_person, stg_condition, stg_medication, stg_encounter
│   │   └── marts/              # gold_records, review_records (live)
│   └── dbt_project.yml
├── dagster_pipelines/
│   ├── assets.py               # 8 SDAs: fhir_s3_upload → snowflake_raw_tables →
│   │                           #   dbt_staging_models → condition_enrichments +
│   │                           #   medication_enrichments → ai_enrichment_verdicts →
│   │                           #   gold_review_routing → dbt_mart_models
│   └── definitions.py          # Dagster Definitions entry point
├── workspace.yaml              # dagster dev -m dagster_pipelines
├── streamlit_app/              # Dashboard (Phase 2)
└── tests/                      # pytest unit tests
```

---

## Future Enhancements

**[Priority 1] RAG with Clinical Guidelines**
Instead of the LLM reasoning from training data alone, retrieve the current clinical guideline — ACC/AHA cardiovascular standards, ADA diabetes management, SAMHSA behavioral health protocols — and include it directly in the enrichment prompt. The LLM then reasons against authoritative, current literature rather than potentially outdated training knowledge. Implementation requires a vector database (Pinecone) to store and retrieve guideline embeddings at inference time.

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
