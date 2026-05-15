"""
LLM-as-Judge scaffold v0.

The judge receives an EnrichmentResult (from enricher.py) and independently
re-evaluates it, returning a JudgeVerdict. This is a second Claude call with
a different system prompt — the judge should NOT see the enricher's rationale
to avoid anchoring bias.

TODO (Eric): write JUDGE_SYSTEM_PROMPT — frame Claude as a skeptical peer
             reviewer, not the enricher. Define what counts as disagreement
             per category and when to flag corrected_confidence.
TODO (Eric): decide anchoring strategy — pass rationale or hide it?
             Current scaffold hides rationale (blind review). Change if needed.
"""

from __future__ import annotations

import os

import anthropic
from dotenv import load_dotenv

from ai_layer.models import EnrichmentResult, JudgeVerdict

load_dotenv()

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# TODO (Eric): write the judge system prompt.
# The judge's job is to challenge the enricher, not confirm it.
# Define: what triggers disagreement, scoring rubric, clinical standards.
# Keep it >1024 tokens to cache.
# ---------------------------------------------------------------------------
JUDGE_SYSTEM_PROMPT = """
You are a senior clinical quality auditor at a health data organization. Your
role is to review AI-generated enrichment scores for EHR records and flag
cases where the scores are inflated, deflated, or clinically unjustified.

You are a skeptic, not a rubber stamp. Your default posture is to question
high scores (above 0.80) and low scores (below 0.30) unless the record
clearly justifies them. You review scores only — rationale text is hidden
from you to prevent anchoring bias.

## What You Are Reviewing

Each record has been scored across 6 clinical categories, each on a 0.0–1.0 scale:

  diagnosis_specificity  — ICD-10 or NDC code specificity
  clinical_urgency       — Implied acuity and severity
  coding_accuracy        — Description-to-code alignment
  medication_appropriateness — Clinical reasonableness of the medication
  drug_condition_alignment   — Recognized drug-condition pairing
  comorbidity_risk           — Multi-condition risk signal

You also see an overall_confidence (weighted average of the 6 scores).

## Disagreement Triggers

Flag disagreement (judge_agrees=False) when ANY of the following are true:

  1. INFLATED SCORE: A category score is >= 0.85 but the record is a synthetic
     Synthea record with a 3-character ICD-10 code, generic description (e.g.
     "diabetes", "hypertension"), or no onset date. Synthea records rarely
     justify maximum specificity scores.

  2. DEFLATED SCORE: A category score is <= 0.25 for a well-known chronic
     condition (T2D, CKD, hypertension, asthma, hypothyroidism) or a textbook
     first-line medication (metformin, lisinopril, atorvastatin, albuterol,
     levothyroxine). These should score at least 0.6 on most dimensions.

  3. INTERNAL INCONSISTENCY: coding_accuracy >= 0.8 but diagnosis_specificity
     <= 0.4 — a specific match on description cannot coexist with a vague code.
     Or: medication_appropriateness >= 0.85 but drug_condition_alignment <= 0.3
     — a clinically appropriate medication should have some condition alignment.

  4. OVERALL DRIFT: overall_confidence diverges by more than 0.20 from the
     simple average of the 6 category scores. This suggests weighting errors.

  5. FLAT SCORING: All 6 category scores are within 0.05 of each other
     (e.g. all between 0.60–0.65). Real clinical records have uneven profiles —
     flat scoring suggests the enricher was not discriminating.

## When to Issue corrected_confidence

Provide corrected_confidence only when judge_agrees=False AND you can
compute a more defensible overall_confidence from the 6 scores you see.
Apply the same weighting rule: diagnosis_specificity and coding_accuracy at
1.5x, all others at 1x. Round to 2 decimal places.

If you disagree but the 6 individual scores are internally consistent (the
issue is only with overall_confidence), correct only overall_confidence and
leave disagreement_categories as an empty list.

## disagreement_categories

List only the specific category names where you disagree with the score.
Use exact names: diagnosis_specificity, clinical_urgency, coding_accuracy,
medication_appropriateness, drug_condition_alignment, comorbidity_risk.
If your disagreement is only with overall_confidence, leave this list empty.

## Output Rules

- Always call the submit_verdict tool. Never respond in free text.
- judge_agrees=True when none of the disagreement triggers above apply.
- disagreement_reason: one to two sentences. Be specific — cite the score
  value and category name. Do not use generic phrases like "scores seem off."
- If judge_agrees=True, set disagreement_reason to null and
  corrected_confidence to null.
"""

JUDGE_TOOL: dict = {
    "name": "submit_verdict",
    "description": "Submit your audit verdict on the enrichment result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "judge_agrees": {
                "type": "boolean",
                "description": "True if you agree with the enricher's scores.",
            },
            "disagreement_categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of category names where you disagree.",
            },
            "disagreement_reason": {
                "type": "string",
                "description": "Required if judge_agrees=False. Clinical reason.",
            },
            "corrected_confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Your corrected overall_confidence, if disagreeing.",
            },
        },
        "required": ["judge_agrees", "disagreement_categories"],
    },
}


def _build_judge_message(result: EnrichmentResult) -> str:
    """Format an EnrichmentResult for the judge.

    Scores are visible; rationale is hidden (blind review).
    TODO (Eric): decide if you want to expose rationale. If yes, add
                 f'  rationale: {cat.rationale}' lines below.
    """
    lines = [
        f"Record type: {result.record_type.upper()}",
        f"Patient ID: {result.patient_id}",
        f"Code: {result.record_code}",
        f"Description: {result.record_description}",
        "",
        "Enrichment scores to audit:",
        f"  diagnosis_specificity score: {result.diagnosis_specificity.score:.2f}",
        f"  clinical_urgency score: {result.clinical_urgency.score:.2f}",
        f"  coding_accuracy score: {result.coding_accuracy.score:.2f}",
        f"  medication_appropriateness score: {result.medication_appropriateness.score:.2f}",
        f"  drug_condition_alignment score: {result.drug_condition_alignment.score:.2f}",
        f"  comorbidity_risk score: {result.comorbidity_risk.score:.2f}",
        f"  overall_confidence: {result.overall_confidence:.2f}",
        "",
        "Audit these scores and submit your verdict.",
    ]
    return "\n".join(lines)


def judge_result(result: EnrichmentResult) -> JudgeVerdict:
    """Run LLM-as-Judge on a single EnrichmentResult."""
    response = _client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": JUDGE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "submit_verdict"},
        messages=[
            {"role": "user", "content": _build_judge_message(result)},
        ],
    )

    tool_block = next(
        (b for b in response.content if b.type == "tool_use"), None
    )
    if tool_block is None:
        raise RuntimeError(
            f"Judge returned no tool_use block for {result.record_code}. "
            f"Stop reason: {response.stop_reason}"
        )

    raw: dict = tool_block.input

    return JudgeVerdict(
        patient_id=result.patient_id,
        record_code=result.record_code,
        record_type=result.record_type,
        judge_agrees=raw["judge_agrees"],
        disagreement_categories=raw.get("disagreement_categories", []),
        disagreement_reason=raw.get("disagreement_reason"),
        corrected_confidence=raw.get("corrected_confidence"),
    )


def judge_batch(
    results: list[EnrichmentResult],
    *,
    stop_on_error: bool = False,
) -> tuple[list[JudgeVerdict], list[dict]]:
    """Judge a list of EnrichmentResults. Returns (verdicts, errors)."""
    verdicts: list[JudgeVerdict] = []
    errors: list[dict] = []

    for result in results:
        try:
            verdicts.append(judge_result(result))
        except Exception as exc:
            errors.append({
                "patient_id": result.patient_id,
                "record_code": result.record_code,
                "error": str(exc),
            })
            if stop_on_error:
                raise

    return verdicts, errors
