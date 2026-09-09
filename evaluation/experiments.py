"""Three controlled experiments with raw repetitions and explicit limitations."""

import asyncio
import json
import statistics
from pathlib import Path

from agent_runtime.context import compact
from agent_runtime.demo_tools import demo_registry
from agent_runtime.models import ContextPolicy, Message, RunRequest
from agent_runtime.persistence import Store
from agent_runtime.runtime import Runtime

from .harness import context_case, metadata

OUT = Path("evaluation/results/experiments.json")


def call(name, **args):
    return {"name": name, "args": args}


def step(id, tool, **kwargs):
    return {"id": id, "tool": tool, **kwargs}


def final_script(calls):
    return [{"type": "tool", **c} for c in calls] + [
        {"type": "final", "result": {"$last_observation": True}}
    ]


def stats(values):
    ordered = sorted(values)
    return {
        "n": len(values),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "min": min(values),
        "max": max(values),
        "p95_nearest_rank": ordered[max(0, __import__("math").ceil(len(ordered) * 0.95) - 1)],
    }


async def experiment_a(runtime):
    steps = [
        step(f"s{i}", call("http_mock", resource=resource, delay_ms=80))
        for i, resource in enumerate(("alpha", "beta", "gamma"))
    ]
    rows = []
    for repetition in range(7):
        for parallel in [False, True] if repetition % 2 == 0 else [True, False]:
            state = await runtime.run(RunRequest(mode="pipeline", steps=steps, parallel=parallel))
            assert state.status == "SUCCESS"
            rows.append(
                {
                    "repetition": repetition,
                    "parallel": parallel,
                    "latency_ms": state.latency_ms,
                    "tool_calls": state.tool_call_count,
                    "values": [s["value"]["value"] for s in state.final_result["steps"].values()],
                }
            )
    seq = stats([r["latency_ms"] for r in rows if not r["parallel"]])
    par = stats([r["latency_ms"] for r in rows if r["parallel"]])
    failure = await runtime.run(
        RunRequest(
            mode="pipeline",
            steps=[
                step("slow", call("http_mock", scenario="timeout")),
                step("fast", call("http_mock", resource="beta", delay_ms=10)),
            ],
        )
    )
    return {
        "fixture": "3 independent httpx.MockTransport calls, each asyncio.sleep(80ms); 7 alternating paired repetitions",
        "sequential_ms": seq,
        "parallel_ms": par,
        "median_speedup": seq["median"] / par["median"],
        "rows": rows,
        "timeout_probe": {
            "status": failure.status.value,
            "latency_ms": failure.latency_ms,
            "errors": [e.model_dump(mode="json") for e in failure.errors],
            "result": failure.final_result,
        },
        "trade_off": "Parallelism helps independent I/O waits, uses concurrent slots, and does not remove the slowest deadline or required-step failures. These are synthetic delays, not internet benchmarks.",
    }


async def experiment_b():
    rows = []
    for turns in (5, 10, 20, 40):
        for strategy in ("naive", "structured"):
            runs = [
                context_case(
                    {
                        "id": f"{turns}-{strategy}",
                        "split": "experiment",
                        "request": {"turns": turns, "strategy": strategy, "token_budget": 400},
                    }
                )
                for _ in range(20)
            ]
            rows.append(
                {
                    "turns": turns,
                    "strategy": strategy,
                    "latency_ms": stats([r["latency_ms"] for r in runs]),
                    "context_bytes": runs[0]["context_bytes"],
                    "estimated_context_tokens": runs[0]["estimated_context_tokens"],
                    "facts_retained": runs[0]["fact_hits"],
                    "facts_total": runs[0]["fact_total"],
                    "task_success_rate": sum(r["task_success"] for r in runs) / len(runs),
                    "raw_runs": runs,
                }
            )
    overflow = compact(
        [Message(content="latest request", facts={f"entity_{i}": "x" * 300 for i in range(20)})],
        ContextPolicy(token_budget=128),
    )
    return {
        "fixture": "5/10/20/40 turns, 2 messages per turn; 4 explicitly annotated synthetic facts; 400 estimated-token budget; 20 repetitions",
        "rows": rows,
        "provider_token_consumption": None,
        "cost_usd": None,
        "bad_case": {
            "description": "Important facts alone exceed 128-token budget; hard budget takes priority.",
            "facts_kept": len(overflow.facts),
            "facts_dropped": overflow.dropped_facts,
            "estimated_tokens": overflow.estimated_tokens,
        },
        "trade_off": "Structured compaction preserves explicit old facts and takes additional CPU/context space. This does not test automatic fact extraction, open-domain summarization or real model accuracy.",
    }


async def experiment_c(runtime):
    tasks = []
    for i in range(6):
        tool = call("calculator", expression=f"{i + 2}*{i + 5}")
        tasks.append(
            {
                "id": f"single-{i}",
                "family": "single",
                "calls": [tool],
                "steps": [step("answer", tool)],
                "answer": {"value": (i + 2) * (i + 5)},
            }
        )
    for i in range(3):
        a, b = call("http_mock", resource="alpha"), call("http_mock", resource="beta")
        analysis = call("data_analysis", values=[10, 20, i])
        tasks.append(
            {
                "id": f"aggregate-{i}",
                "family": "dependent",
                "calls": [a, b, analysis],
                "steps": [
                    step("a", a),
                    step("b", b),
                    step(
                        "answer",
                        call("data_analysis", values=[{"$ref": "a.value"}, {"$ref": "b.value"}, i]),
                        depends_on=["a", "b"],
                    ),
                ],
                "answer": {"count": 3, "sum": 30 + i, "mean": (30 + i) / 3, "min": i, "max": 20},
            }
        )
    for resource, value in [("alpha", 10), ("beta", 20), ("gamma", 30)]:
        fetch = call("http_mock", resource=resource)
        calc = call("calculator", expression=f"{value}*2")
        tasks.append(
            {
                "id": f"branch-{resource}",
                "family": "conditional",
                "calls": [fetch, calc],
                "steps": [
                    step("fetch", fetch),
                    step(
                        "answer",
                        calc,
                        depends_on=["fetch"],
                        when={"ref": "fetch.value", "equals": value},
                    ),
                    step(
                        "unused",
                        call("calculator", expression="0"),
                        depends_on=["fetch"],
                        when={"ref": "fetch.value", "equals": 0},
                    ),
                ],
                "answer": {"value": value * 2},
            }
        )
    rows = []
    for repeat in range(3):
        for task in tasks:
            for mode in ("direct", "react", "pipeline"):
                if mode == "direct" and task["family"] != "single":
                    continue
                request = {"mode": mode}
                if mode == "direct":
                    request["tool"] = task["calls"][0]
                elif mode == "react":
                    request["mock_script"] = final_script(task["calls"])
                else:
                    request["steps"] = task["steps"]
                state = await runtime.run(RunRequest.model_validate(request))
                result = (
                    state.final_result["steps"]["answer"]["value"]
                    if mode == "pipeline" and state.final_result
                    else state.final_result
                )
                rows.append(
                    {
                        "repeat": repeat,
                        "id": task["id"],
                        "family": task["family"],
                        "mode": mode,
                        "success": state.status == "SUCCESS" and result == task["answer"],
                        "latency_ms": state.latency_ms,
                        "tool_calls": state.tool_call_count,
                        "llm_calls": state.llm_call_count,
                    }
                )
    groups = {}
    for mode in ("direct", "react", "pipeline"):
        for family in ("all", "single", "dependent", "conditional"):
            subset = [
                r for r in rows if r["mode"] == mode and (family == "all" or r["family"] == family)
            ]
            if subset:
                groups[f"{mode}/{family}"] = {
                    "successes": sum(r["success"] for r in subset),
                    "runs": len(subset),
                    "latency_ms": stats([r["latency_ms"] for r in subset]),
                    "mean_tool_calls": statistics.mean(r["tool_calls"] for r in subset),
                    "mean_llm_calls": statistics.mean(r["llm_calls"] for r in subset),
                }
    bad = await runtime.run(
        RunRequest(
            mode="direct",
            tool=call("http_mock", resource="alpha"),
            user_request="Fetch alpha and beta and sum their values",
        )
    )
    return {
        "fixture": "12 declared tasks: 6 single, 3 dependent aggregation, 3 conditional. 3 repetitions. Mock scripts supplied by harness.",
        "groups": groups,
        "rows": rows,
        "provider_tokens": None,
        "bad_case": {
            "description": "A single direct fetch cannot satisfy a two-tool aggregation task.",
            "runtime_status": bad.status.value,
            "actual_result": bad.final_result,
            "desired_result": {"sum": 30},
            "task_success": False,
        },
        "trade_off": "Compare all three only on matched single-tool tasks. Direct is N/A for dependent/conditional tasks; ReAct fixtures do not measure model reasoning or network overhead. Pipeline and ReAct use extra state/persistence operations.",
    }


async def main():
    store = Store("sqlite+aiosqlite:///./runtime-data/experiments.db")
    await store.initialize()
    runtime = Runtime(demo_registry(), store)
    try:
        results = {
            **metadata(),
            "A": await experiment_a(runtime),
            "B": await experiment_b(),
            "C": await experiment_c(runtime),
        }
        await asyncio.to_thread(
            OUT.write_text, json.dumps(results, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps(
                {
                    "A_speedup": results["A"]["median_speedup"],
                    "B_rows": [
                        {k: v for k, v in r.items() if k != "raw_runs"}
                        for r in results["B"]["rows"]
                    ],
                    "C_groups": results["C"]["groups"],
                },
                indent=2,
            )
        )
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
