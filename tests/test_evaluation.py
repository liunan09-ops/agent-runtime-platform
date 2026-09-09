import json

from agent_runtime.models import RunRequest
from evaluation.harness import aggregate, context_case, dataset


def test_dataset_version_split_and_live_isolation():
    data, manifest = dataset()
    assert len(data["cases"]) == manifest["count"] == 48
    assert len({c["id"] for c in data["cases"]}) == 48
    assert sum(c["split"] == "held-out" for c in data["cases"]) == 16
    for case in data["cases"]:
        if case["live_eligible"]:
            assert case["split"] == "held-out" and case["request"]["user_request"]
        if case["kind"] != "context":
            RunRequest.model_validate(case["request"])
    assert "api_key" not in json.dumps(data).lower()


def test_context_metrics_detect_lost_facts_not_only_terminal_status():
    rows = [
        context_case(
            {
                "id": strategy,
                "split": "development",
                "request": {"turns": 40, "strategy": strategy, "token_budget": 400},
            }
        )
        for strategy in ["naive", "structured"]
    ]
    assert not rows[0]["task_success"] and rows[1]["task_success"]
    assert rows[0]["fact_hits"] == 2 and rows[1]["fact_hits"] == 4
    result = aggregate(rows)
    assert result["task_success"] == {"hits": 1, "total": 2, "rate": 0.5}
    assert result["context_fact_retention"]["rate"] == 0.75
    assert result["tool_selection_accuracy"]["rate"] is None
