import json

import pytest

from quality import judge_eval as je


def enr(i, rtype="condition", desc="x (disorder)"):
    base = {"patient_id": f"p{i}", "record_code": str(i), "record_type": rtype, "record_description": desc,
            "overall_confidence": 0.6}
    base.update({c: {"score": 0.5, "rationale": ""} for c in je.CATEGORIES})
    return base


def test_confusion_counts_and_kappa():
    labels = [True, True, False, False]       # acceptable?
    disagrees = [False, True, True, False]    # judge flag
    c = je.confusion(labels, disagrees)
    assert c == {"tp": 1, "fn": 1, "fp": 1, "tn": 1}
    assert je.cohen_kappa(c) == pytest.approx(0.0)
    perfect = je.confusion([True, False], [False, True])
    assert je.cohen_kappa(perfect) == pytest.approx(1.0)


def test_stratified_sample_is_deterministic_and_balanced():
    pool = ([enr(i, "medication") for i in range(40)]
            + [enr(100 + i, desc="employment (finding)") for i in range(40)]
            + [enr(200 + i, desc="asthma (disorder)") for i in range(40)])
    a, b = je.stratified_sample(pool, 20, seed=3), je.stratified_sample(pool, 20, seed=3)
    assert [r["record_code"] for r in a] == [r["record_code"] for r in b]
    assert sum(r["record_type"] == "medication" for r in a) == 10
    assert sum("(finding)" in r["record_description"] for r in a) == 5


def test_sample_then_score_round_trip(tmp_path):
    recs = [enr(i, "medication" if i % 2 else "condition", "chronic pain (finding)" if i % 3 == 0 else "x (disorder)")
            for i in range(30)]
    verdicts = [{"patient_id": r["patient_id"], "record_code": r["record_code"], "record_type": r["record_type"],
                 "judge_agrees": r["record_code"] != "1"} for r in recs]
    export = tmp_path / "e.json"
    export.write_text(json.dumps({"enrichment_results": recs, "judge_verdicts": verdicts}))
    out = tmp_path / "s.csv"
    je.cmd_sample(export, out, 10, 5)
    rows = out.read_text().splitlines()
    assert len(rows) == 11 and "acceptable" in rows[0]
    labeled = tmp_path / "l.csv"
    labeled.write_text("\n".join(r if i == 0 else r.replace(",,", ",Y,", 1) for i, r in enumerate(rows)))
    je.cmd_score(export, labeled, seed=5)  # must not raise
