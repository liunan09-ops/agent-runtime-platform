"""Run frozen tasks and produce raw evidence. All metrics disclose their denominators."""

import argparse
import asyncio
import hashlib
import json
import platform
import re
import statistics
import subprocess
import time
from collections import Counter
from pathlib import Path

from agent_runtime.context import compact, render_context
from agent_runtime.demo_tools import demo_registry
from agent_runtime.models import ContextPolicy, RunRequest, utcnow
from agent_runtime.persistence import Store
from agent_runtime.runtime import Runtime, lookup_ref

from .fixtures import FACTS, long_context

ROOT = Path(__file__).resolve().parent


def dataset():
    path = ROOT / "datasets/tasks-v1.json"
    manifest = json.loads((ROOT / "datasets/manifest-v1.json").read_text())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["sha256"], (
        "Dataset hash changed"
    )
    return json.loads(path.read_text()), manifest


def metadata():
    return {
        "recorded_at": utcnow(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "timing": "time.perf_counter; wall latency includes runtime persistence; no monetary price configured",
    }


def check_state(state, expected):
    output = state.model_dump(mode="json")
    checks = {}
    for path, wanted in expected.items():
        try:
            actual = lookup_ref(path, output)
            checks[path] = actual == wanted
        except (KeyError, IndexError, TypeError, ValueError):
            checks[path] = False
    return checks


def call_metrics(state, expected):
    actual = [h.call.model_dump(mode="json") for h in state.tool_history]
    # Compare multisets, allowing independent DAG calls to finish in either order.
    names_actual = Counter(c["name"] for c in actual)
    names_expected = Counter(c["name"] for c in expected)
    args_actual = Counter(json.dumps(c, sort_keys=True) for c in actual)
    args_expected = Counter(json.dumps(c, sort_keys=True) for c in expected)
    denominator = max(len(expected), len(actual))
    return {
        "selection_hits": sum((names_actual & names_expected).values()),
        "argument_hits": sum((args_actual & args_expected).values()),
        "call_accuracy_denominator": denominator,
        "selected_calls": actual,
    }


def context_case(case):
    config = case["request"]
    messages = long_context(config["turns"])
    start = time.perf_counter()
    state = compact(
        messages, ContextPolicy(strategy=config["strategy"], token_budget=config["token_budget"])
    )
    elapsed = (time.perf_counter() - start) * 1000
    rendered = render_context(state)
    # A transparent synthetic downstream extraction task, not an LLM quality claim.
    extracted = dict(state.facts)
    for message in state.messages:
        extracted.update(
            dict(re.findall(r"\b(owner|budget|region|deadline)=([A-Za-z0-9]+)", message.content))
        )
    retained = sum(extracted.get(k) == v for k, v in FACTS.items())
    return {
        "id": case["id"],
        "split": case["split"],
        "kind": "context",
        "strategy": config["strategy"],
        "turns": config["turns"],
        "task_success": retained == len(FACTS),
        "fact_hits": retained,
        "fact_total": len(FACTS),
        "context_bytes": len(rendered.encode()),
        "estimated_context_tokens": state.estimated_tokens,
        "input_messages": len(messages),
        "retained_messages": len(state.messages),
        "latency_ms": elapsed,
        "llm_call_count": 0,
        "tool_call_count": 0,
        "token_usage": None,
        "cost_usd": None,
        "checks": {"all_required_facts": retained == len(FACTS)},
        "source": "deterministic context extraction fixture",
    }


async def run_case(runtime, case, live=False):
    if case["kind"] == "context":
        return context_case(case)
    request = dict(case["request"])
    if live:
        request = {
            "mode": "react",
            "provider": "deepseek",
            "user_request": request["user_request"],
            "timeout_s": 150,
            "llm_timeout_s": 60,
            "max_steps": 8,
            "llm_retries": 1,
        }
    state = await runtime.run(RunRequest.model_validate(request))
    checks = check_state(state, case.get("live_expected") or case["expected"])
    replay_state = None
    if case["kind"] == "replay":
        replay_state = (await runtime.replay(state.request_id)).state
        checks["replay_final_result"] = replay_state.final_result == state.final_result
        checks["replay_status"] = replay_state.status == state.status
        checks["replay_no_calls"] = replay_state.tool_call_count == replay_state.llm_call_count == 0
    trace = await runtime.store.get(state.request_id)
    source = "live-deepseek" if live else "deterministic-mock"
    trace_dir = ROOT / "results" / f"{source}-traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / f"{case['id']}.json").write_text(trace.model_dump_json(indent=2) + "\n")
    return {
        "id": case["id"],
        "split": case["split"],
        "kind": case["kind"],
        "mode": request["mode"],
        "task_success": all(checks.values()),
        "checks": checks,
        "status": state.status.value,
        "workflow_completed": state.status == "SUCCESS" if request["mode"] == "pipeline" else None,
        "recovery_case": bool(
            set(case["tags"]) & {"recovery", "retry", "fallback", "timeout", "malformed"}
        )
        or bool(state.errors),
        "latency_ms": state.latency_ms,
        "llm_call_count": state.llm_call_count,
        "tool_call_count": state.tool_call_count,
        "token_usage": state.token_usage,
        "cost_usd": state.cost_usd,
        "final_result": state.final_result,
        "errors": [e.model_dump(mode="json") for e in state.errors],
        "trace": f"{source}-traces/{case['id']}.json",
        "source": source,
        **call_metrics(state, case["expected_calls"]),
    }


def ratio(hits, total):
    return {"hits": hits, "total": total, "rate": hits / total if total else None}


def aggregate(rows):
    call_denom = sum(r.get("call_accuracy_denominator", 0) for r in rows)
    workflow = [r for r in rows if r.get("mode") == "pipeline"]
    recovery = [r for r in rows if r.get("recovery_case")]
    context = [r for r in rows if r["kind"] == "context"]
    run_rows = [r for r in rows if r["kind"] != "context"]
    return {
        "task_success": ratio(sum(r["task_success"] for r in rows), len(rows)),
        "tool_selection_accuracy": ratio(sum(r.get("selection_hits", 0) for r in rows), call_denom),
        "tool_argument_accuracy": ratio(sum(r.get("argument_hits", 0) for r in rows), call_denom),
        "workflow_completion": ratio(sum(r["workflow_completed"] for r in workflow), len(workflow)),
        "recovery_success": ratio(sum(r["task_success"] for r in recovery), len(recovery)),
        "context_fact_retention": ratio(
            sum(r["fact_hits"] for r in context), sum(r["fact_total"] for r in context)
        ),
        "latency_ms": {
            "mean": statistics.mean(r["latency_ms"] for r in rows),
            "median": statistics.median(r["latency_ms"] for r in rows),
            "max": max(r["latency_ms"] for r in rows),
        },
        "llm_call_count": sum(r["llm_call_count"] for r in rows),
        "tool_call_count": sum(r["tool_call_count"] for r in rows),
        "terminal_success_count": sum(r["status"] == "SUCCESS" for r in run_rows),
        "token_usage": {
            "total_tokens": sum((r.get("token_usage") or {}).get("total_tokens", 0) for r in rows)
        }
        if any(r.get("token_usage") for r in rows)
        else None,
        "cost_usd": None,
    }


async def evaluate(live=False, split="all"):
    data, manifest = dataset()
    cases = [
        c
        for c in data["cases"]
        if (split == "all" or c["split"] == split) and (not live or c["live_eligible"])
    ]
    if live:
        assert all(c["split"] == "held-out" for c in cases)
    store = Store("sqlite+aiosqlite:///./runtime-data/evaluation.db")
    await store.initialize()
    runtime = Runtime(demo_registry(), store)
    rows = []
    try:
        for case in cases:
            row = await run_case(runtime, case, live)
            rows.append(row)
            print(
                json.dumps(
                    {
                        "id": case["id"],
                        "success": row["task_success"],
                        "latency_ms": round(row["latency_ms"], 2),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            # Save incrementally so real failed/interrupted attempts remain reviewable.
            report = {
                **metadata(),
                "dataset": manifest,
                "source": "live-deepseek" if live else "deterministic-mock",
                "split": split,
                "metrics": aggregate(rows),
                "rows": rows,
                "metric_notes": {
                    "task_success": "Passes all semantic assertions, including expected safe failure for negative tasks; context fixtures require all four facts.",
                    "tool_argument_accuracy": "Exact declared name+argument multiset; semantically equivalent SQL/arithmetic can score lower.",
                    "workflow_completion": "SUCCESS terminal pipeline runs / all pipeline runs, including deliberately failing workflows.",
                    "recovery_success": "Expected recovery OR safe terminal failure contract on error cases, not always conversion to SUCCESS.",
                    "tokens": "Only provider-reported usage; context estimator is reported separately. No reliable monetary cost.",
                },
            }
            report["by_split"] = {
                s: aggregate([r for r in rows if r["split"] == s])
                for s in sorted({r["split"] for r in rows})
            }
            output = (
                ROOT
                / "results"
                / ("live-deepseek-held-out.json" if live else f"deterministic-{split}.json")
            )
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    finally:
        await store.close()
    print(json.dumps(report["metrics"], indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--split", choices=["all", "development", "held-out"], default="all")
    args = parser.parse_args()
    asyncio.run(evaluate(args.live, "held-out" if args.live else args.split))
