# Copyright (c) 2026 Eric Grynspan. All rights reserved.
"""
Deterministic evaluation of the five judge disagreement triggers.

Why this exists: the v1 judge prompt defines trigger 1 as "score >= 0.85 AND (3-character ICD-10 code OR generic
description OR no onset date)". In the June 2026 run onset_date was never an enrichment input (absent on 174/174
records) and no record carried a 3-character ICD-10 code (0/174), so the qualifier was always true and the trigger
fired on any score >= 0.85. The judge disagreed on 166/166 records. This module applies the qualifiers as written
and is pure (no API calls), so each trigger can be unit tested and audited offline.

Status: NOT wired into router.route(). Wiring changes the published Gold rate and needs validation against a
hand-labeled sample first (see README "Validation status").
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

CATEGORIES = (
    "diagnosis_specificity",
    "clinical_urgency",
    "coding_accuracy",
    "medication_appropriateness",
    "drug_condition_alignment",
    "comorbidity_risk",
)

# Rubric examples; extend only after the labeled-sample review.
GENERIC_DESCRIPTIONS = frozenset({"diabetes", "hypertension", "asthma", "pain", "infection"})
WELL_KNOWN = (
    "diabetes", "chronic kidney", "hypertension", "asthma", "hypothyroid",
    "metformin", "lisinopril", "atorvastatin", "albuterol", "levothyroxine",
)
# SNOMED semantic tags that are not diseases. Concepts with these tags (employment, housing, cough, prediabetes,
# BMI 30+, chronic pain...) carry no ICD-style specificity, so trigger 3 (coding_accuracy high, specificity low)
# is structurally unsatisfiable-to-avoid for them. The June 2026 export applied this exemption retroactively
# (52/52 finding/situation/person records, 0 disorder records) outside the repo; it is now explicit and tested.
NON_DISORDER_TAGS = frozenset({"finding", "situation", "person"})

_TAG = re.compile(r"\(([^)]*)\)\s*$")
_ICD3 = re.compile(r"^[A-Za-z]\d{2}$")


def semantic_tag(description: str) -> str | None:
    m = _TAG.search(description or "")
    return m.group(1).strip().lower() if m else None


@dataclass(frozen=True)
class TriggerResult:
    t1_inflated: bool
    t2_deflated: bool
    t3_inconsistent: bool
    t4_drift: bool
    t5_flat: bool

    @property
    def fired(self) -> list[str]:
        return [n for n, v in (("T1", self.t1_inflated), ("T2", self.t2_deflated), ("T3", self.t3_inconsistent),
                               ("T4", self.t4_drift), ("T5", self.t5_flat)) if v]

    @property
    def disagrees(self) -> bool:
        return bool(self.fired)


def evaluate_triggers(
    scores: dict[str, float], overall_confidence: float, code: str, description: str
) -> TriggerResult:
    s = {c: float(scores[c]) for c in CATEGORIES}
    vals = list(s.values())
    desc = (description or "").lower()
    base = _TAG.sub("", desc).strip()
    generic = base in GENERIC_DESCRIPTIONS or bool(_ICD3.match(code or ""))
    known = any(k in desc for k in WELL_KNOWN)
    non_disorder = semantic_tag(description) in NON_DISORDER_TAGS

    t3 = (s["coding_accuracy"] >= 0.8 and s["diagnosis_specificity"] <= 0.4 and not non_disorder) or (
        s["medication_appropriateness"] >= 0.85 and s["drug_condition_alignment"] <= 0.3)
    return TriggerResult(
        t1_inflated=any(v >= 0.85 for v in vals) and generic,
        t2_deflated=any(v <= 0.25 for v in vals) and known,
        t3_inconsistent=t3,
        t4_drift=abs(float(overall_confidence) - sum(vals) / len(vals)) > 0.20,
        t5_flat=(max(vals) - min(vals)) <= 0.05 + 1e-9,  # tolerance for float spread
    )


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion (valid for small n and extreme p)."""
    if n <= 0:
        raise ValueError("n must be positive")
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)
