from shiyi_api.benchmark import METHODS, evaluate, scenarios


def test_synthetic_benchmark_is_deterministic_and_paired(monkeypatch, tmp_path):
    untouched = tmp_path / "must-not-open.sqlite3"
    monkeypatch.setenv("SHIYI_DB_PATH", str(untouched))
    first = evaluate(seed=42, per_cohort=2)
    second = evaluate(seed=42, per_cohort=2)
    assert first == second
    assert not untouched.exists()
    assert first["scenario_count"] == 12
    assert first["rankings"] == 48
    assert first["is_synthetic"] is True
    for case in scenarios(42, 2):
        group = [r for r in first["ranking_rows"] if r["case_id"] == case.case_id]
        assert {r["method"] for r in group} == set(METHODS)
        assert all(r["top1"] in case.utility and r["regret"] >= 0 for r in group)
        assert next(r for r in group if r["method"] == "no_memory")["feedback_recalled"] == 0
    assert all(row["harness"] == row["expected"] for row in first["gate_rows"])
    assert first["gates"]["ungated_counterfactual"]["fp"] > 0
