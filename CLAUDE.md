# ai-healthcare-pipeline (P3)

## Project
Clinical AI governance engine. FHIR bundles → S3 → Snowflake → Claude enrichment + LLM-as-Judge + Structured Rules Engine → routing.

## Key Numbers
- 174 enriched | 166 judged | 13 gold clean (7.8%) | 39 review low conf | 114 review conflict
- 6 governance categories | CI green | v1.0.0 tagged

## Stack
| Layer | Tool |
|---|---|
| Ingestion | FHIR bundles → S3 (`ai-healthcare-pipeline-eric`) |
| Warehouse | Snowflake — **TRIAL EXPIRED Jun 9 2026, add billing** |
| AI layer | `ai_layer/` — Claude enrichment + confidence scoring + LLM-as-Judge |
| Rules | Structured Rules Engine (6 categories) |
| Quality | `quality/` — Great Expectations |
| Orchestration | Dagster (`workspace.yaml`) |
| Dashboard | Streamlit (`streamlit_app/`) |

## Key Commands
```
make lint              # flake8, max-line-length 120
make test              # pytest tests/ -v --cov
make dagster           # dagster dev
make streamlit         # streamlit run streamlit_app/app.py
```

## Data State
Snowflake export COMPLETE — all tables + GOLD_RECORDS.csv + REVIEW_RECORDS.csv + ROUTING_SUMMARY.json
Backed up: Dropbox/Data Engineering/Projects/Clinical AI Governance Engine/snowflake_export/

## Python
Full path: `C:/Users/ericg/AppData/Local/Programs/Python/Python313/python.exe`

## Repo
Public: github.com/ericg1212/ai-healthcare-pipeline | v1.0.0 tagged | Branch protected
