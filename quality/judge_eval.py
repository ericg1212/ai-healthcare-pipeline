# Copyright (c) 2026 Eric Grynspan. All rights reserved.
"""Hand-labeled validation of the judge and the Gold gate (offline, no API calls).

Two steps, both deterministic:
  1. python -m quality.judge_eval sample EXPORT.json OUT.csv [--n 50] [--seed 7]
     Writes a BLIND stratified sample (no judge verdict shown) with an empty `acceptable` column.
     Label Y if every score is clinically defensible for that record, N if any score is not.
  2. python -m quality.judge_eval score EXPORT.json LABELED.csv
     Joins labels to the saved verdicts and reports sensitivity / specificity / precision / kappa with 95% Wilson
     intervals, for the judge alone and for the Gold gate (judge agrees AND confidence >= 0.55).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from ai_layer.judge_triggers import CATEGORIES, NON_DISORDER_TAGS, semantic_tag, wilson_interval

THRESHOLD = 0.55  # ai_layer.router.CONFIDENCE_THRESHOLD
FIELDS = ["sample_id", "record_type", "record_code", "record_description", *CATEGORIES, "overall_confidence",
          "acceptable", "notes"]


def _key(r: dict) -> tuple[str, str, str]:
    return r["patient_id"], r["record_code"], r["record_type"]


def stratified_sample(enrichments: list[dict], n: int = 50, seed: int = 7) -> list[dict]:
    """Half medications, half conditions; conditions split evenly between disorder and non-disorder tags."""
    rng = random.Random(seed)
    meds = [e for e in enrichments if e["record_type"] == "medication"]
    cond = [e for e in enrichments if e["record_type"] == "condition"]
    non = [e for e in cond if semantic_tag(e["record_description"]) in NON_DISORDER_TAGS]
    dis = [e for e in cond if semantic_tag(e["record_description"]) not in NON_DISORDER_TAGS]

    def take(pool: list[dict], k: int) -> list[dict]:
        return rng.sample(pool, min(k, len(pool)))

    half, quarter = n // 2, n // 4
    chosen = take(meds, half) + take(non, quarter) + take(dis, n - half - quarter)
    rng.shuffle(chosen)
    return chosen


def confusion(labels: list[bool], disagrees: list[bool]) -> dict[str, int]:
    """labels: True = acceptable. A good judge disagrees exactly when the record is NOT acceptable."""
    tp = sum((not a) and d for a, d in zip(labels, disagrees))      # unacceptable, flagged
    fn = sum((not a) and (not d) for a, d in zip(labels, disagrees))  # unacceptable, missed
    fp = sum(a and d for a, d in zip(labels, disagrees))            # acceptable, flagged
    tn = sum(a and (not d) for a, d in zip(labels, disagrees))      # acceptable, passed
    return {"tp": tp, "fn": fn, "fp": fp, "tn": tn}


def cohen_kappa(c: dict[str, int]) -> float:
    n = sum(c.values())
    if n == 0:
        return float("nan")
    po = (c["tp"] + c["tn"]) / n
    pe = ((c["tp"] + c["fn"]) * (c["tp"] + c["fp"]) + (c["fp"] + c["tn"]) * (c["fn"] + c["tn"])) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def _rate(k: int, n: int) -> str:
    if n == 0:
        return "n/a (0 cases)"
    lo, hi = wilson_interval(k, n)
    return f"{k}/{n} = {k / n:.0%} (95% CI {lo:.0%}-{hi:.0%})"


def report(title: str, c: dict[str, int]) -> None:
    print(f"\n{title}")
    print("  sensitivity (flags unacceptable):", _rate(c["tp"], c["tp"] + c["fn"]))
    print("  specificity (passes acceptable): ", _rate(c["tn"], c["tn"] + c["fp"]))
    print("  precision of a flag:             ", _rate(c["tp"], c["tp"] + c["fp"]))
    print(f"  Cohen's kappa: {cohen_kappa(c):.2f}")


def load(export: Path) -> dict:
    return json.loads(export.read_text(encoding="utf-8"))


def cmd_sample(export: Path, out: Path, n: int, seed: int) -> None:
    d = load(export)
    judged = {_key(v) for v in d["judge_verdicts"]}
    pool = [e for e in d["enrichment_results"] if _key(e) in judged]
    rows = stratified_sample(pool, n, seed)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, e in enumerate(rows, 1):
            w.writerow({"sample_id": i, "record_type": e["record_type"], "record_code": e["record_code"],
                        "record_description": e["record_description"],
                        **{c: e[c]["score"] for c in CATEGORIES}, "overall_confidence": e["overall_confidence"],
                        "acceptable": "", "notes": ""})
    print(f"wrote {len(rows)} blind rows to {out} (seed {seed}); label `acceptable` Y/N; keep the same seed to rejoin.")


def cmd_score(export: Path, labeled: Path, seed: int = 7) -> None:
    d = load(export)
    verdicts = {_key(v): v for v in d["judge_verdicts"]}
    enr = {_key(e): e for e in d["enrichment_results"]}
    with open(labeled, newline="", encoding="utf-8") as f:
        n_rows = sum(1 for _ in csv.DictReader(f))
    sample = stratified_sample([e for k, e in enr.items() if k in verdicts], n_rows, seed)
    labels, disagree, gold_pass = [], [], []
    with open(labeled, newline="", encoding="utf-8") as f:
        for row, e in zip(csv.DictReader(f), sample):
            if row["record_code"] != e["record_code"]:
                raise SystemExit("labeled sheet does not match the seeded sample: use the same seed and export")
            ans = row["acceptable"].strip().upper()
            if ans not in ("Y", "N"):
                continue
            v = verdicts[_key(e)]
            labels.append(ans == "Y")
            disagree.append(not v["judge_agrees"])
            gold_pass.append(v["judge_agrees"] and e["overall_confidence"] >= THRESHOLD)
    print(f"labeled rows used: {len(labels)} | acceptable: {sum(labels)}")
    report("JUDGE (v1 verdicts): disagree = flag", confusion(labels, disagree))
    report("GOLD GATE: not-Gold = flag", confusion(labels, [not g for g in gold_pass]))
    ok_gold = [a for a, g in zip(labels, gold_pass) if g]
    print("\nGold precision (acceptable among Gold):", _rate(sum(ok_gold), len(ok_gold)))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("export", type=Path)
    s.add_argument("out", type=Path)
    s.add_argument("--n", type=int, default=50)
    s.add_argument("--seed", type=int, default=7)
    c = sub.add_parser("score")
    c.add_argument("export", type=Path)
    c.add_argument("labeled", type=Path)
    c.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    if a.cmd == "sample":
        cmd_sample(a.export, a.out, a.n, a.seed)
    else:
        cmd_score(a.export, a.labeled, a.seed)


if __name__ == "__main__":
    main()
