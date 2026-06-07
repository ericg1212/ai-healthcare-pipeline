"""
Pydantic schemas for AI enrichment layer v0.

Input records mirror stg_condition / stg_medication staging columns.
EnrichmentResult carries one score per clinical category (6 total).
JudgeVerdict is the LLM-as-Judge assessment of the enrichment.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Input records (mirrors staging tables)
# ---------------------------------------------------------------------------

class ConditionRecord(BaseModel):
    patient_id: str
    condition_code: str
    condition_description: str
    onset_date: date | None = None


class MedicationRecord(BaseModel):
    patient_id: str
    medication_code: str
    medication_description: str
    start_date: date | None = None


# ---------------------------------------------------------------------------
# Enrichment output
# ---------------------------------------------------------------------------

class CategoryScore(BaseModel):
    score: float = Field(ge=0.0, le=1.0, description="Confidence 0–1")
    rationale: str = Field(description="One-sentence clinical rationale")


class EnrichmentResult(BaseModel):
    patient_id: str
    record_type: Literal["condition", "medication"]
    record_code: str
    record_description: str
    onset_date: date | None = None

    diagnosis_specificity: CategoryScore
    clinical_urgency: CategoryScore
    coding_accuracy: CategoryScore
    medication_appropriateness: CategoryScore
    drug_condition_alignment: CategoryScore
    comorbidity_risk: CategoryScore

    overall_confidence: float = Field(ge=0.0, le=1.0)
    enriched_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def confidence_consistency(self) -> EnrichmentResult:
        scores = [
            self.diagnosis_specificity.score,
            self.clinical_urgency.score,
            self.coding_accuracy.score,
            self.medication_appropriateness.score,
            self.drug_condition_alignment.score,
            self.comorbidity_risk.score,
        ]
        avg = sum(scores) / len(scores)
        # Warn if Claude's overall_confidence diverges too far from category avg
        if abs(self.overall_confidence - avg) > 0.25:
            raise ValueError(
                f"overall_confidence {self.overall_confidence:.2f} diverges "
                f">0.25 from category average {avg:.2f}"
            )
        return self


# ---------------------------------------------------------------------------
# LLM-as-Judge verdict
# ---------------------------------------------------------------------------

class JudgeVerdict(BaseModel):
    patient_id: str
    record_code: str
    record_type: Literal["condition", "medication"]

    judge_agrees: bool
    disagreement_categories: list[str] = Field(
        default_factory=list,
        description="Category names where judge disagrees with enricher score",
    )
    disagreement_reason: str | None = None
    corrected_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Judge's corrected overall_confidence, if disagreeing",
    )
    judged_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def disagreement_requires_reason(self) -> JudgeVerdict:
        if not self.judge_agrees and not self.disagreement_reason:
            raise ValueError("disagreement_reason required when judge_agrees=False")
        return self


# ---------------------------------------------------------------------------
# Gold routing output
# ---------------------------------------------------------------------------

class GoldRecord(BaseModel):
    patient_id: str
    record_type: Literal["condition", "medication"]
    record_code: str
    record_description: str
    overall_confidence: float = Field(ge=0.0, le=1.0)
    gold_status: Literal[
        "enriched_clean",
        "enriched_review_conflict",
        "enriched_review_low_confidence",
    ]
    review_reason: str | None = None
    flags_triggered: list[str] = Field(default_factory=list)
    judge_agrees: bool
    corrected_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    routed_at: datetime = Field(default_factory=datetime.utcnow)
