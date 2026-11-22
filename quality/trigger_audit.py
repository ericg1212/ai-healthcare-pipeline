# Copyright (c) 2026 Eric Grynspan. All rights reserved.
"""Offline audit of the judge triggers against a saved enrichment export (no API calls).

Usage: python -m quality.trigger_audit path/to/GOLD_ENRICHMENT_RESULTS.json
Reproduces the published routing from the JSON alone, then reports trigger fire rates and 95% Wilson intervals.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from ai_layer.judge_triggers import CATEGORIES, NON_DISORDER_TAGS, evaluate_triggers, semantic_tag, wilson_interval

THRESHOLD = 0.55  # ai_layer.router.CONFIDENCE_THRESHOLD


def fmt(k: int, n: int) -> str:
    lo, hi = wilson_interval(k, n)
    return f"{k}/{n} = {k / n:.1%} (95% CI {lo:.1%}-{hi:.1%})"


def main(path: Path) -> None:
    d = json.loads(path.read_text(encoding="utf-8"))
    enr = {(e["patient_id"], e["record_code"], e["record_type"]): e for e in d["enrichment_results"]}
    judged = [(enr[(v["patient_id"], v["record_code"], v["record_type"])], v) for v in d["judge_verdicts"]]
    n = len(judged)
    print(f"run {d['run_at']} | enriched {len(enr)} | judged {n} | judge errors {len(d['judge_errors'])}")
    print("raw judge disagrees:", fmt(sum(not v["judge_agrees"] for _, v in judged), n))

    # Reproduce the published export: raw disagreement + retroactive exemption for non-disorder semantic tags.
    exempt = [(e, v) for e, v in judged if semantic_tag(e["record_description"]) in NON_DISORDER_TAGS]
    clean = sum(e["overall_confidence"] >= THRESHOLD for e, _ in exempt)
    print(f"exempt (finding/situation/person): {len(exempt)} -> clean {clean}, low-conf {len(exempt) - clean}, "
          f"conflict {n - len(exempt)}")
    print("published Gold clean:", fmt(clean, n), "| non-exempt records:", n - len(exempt),
          "| exempt tags:", dict(Counter(semantic_tag(e["record_description"]) for e, _ in exempt)))

    # v1-as-executed (qualifiers always true) vs v2-as-written.
    v1 = sum(any(e[c]["score"] >= 0.85 for c in CATEGORIES) for e, _ in judged)
    print("\ntrigger 1 under v1 (any score >= 0.85):", fmt(v1, n))
    fires, passed = Counter(), 0
    for e, _ in judged:
        r = evaluate_triggers({c: e[c]["score"] for c in CATEGORIES}, e["overall_confidence"],
                              e["record_code"], e["record_description"])
        fires.update(r.fired)
        passed += (not r.disagrees) and e["overall_confidence"] >= THRESHOLD
    print("v2 trigger fires:", dict(fires))
    print("v2 projected Gold clean (UNVALIDATED):", fmt(passed, n))
    if not fires:
        print("NOTE: v2 triggers fire on 0 records, so this equals the confidence-gate pass rate,")
        print("      not a quality estimate.")
    print("by record type:", dict(Counter(e["record_type"] for e, _ in judged)))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
