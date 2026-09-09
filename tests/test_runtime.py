import asyncio
import time

import pytest
from pydantic import ValidationError

from agent_runtime.demo_tools import CalcInput, CalcOutput
from agent_runtime.models import RunRequest, RunState, Status
from agent_runtime.registry import Tool


def call(expression="6*7"):
    return {"name": "calculator", "args": {"expression": expression}}


def action(expression="6*7"):
    return {"type": "tool", **call(expression)}


FINAL = {"type": "final", "result": {"$last_observation": True}}


async def test_direct_and_serialization(runtime):
    state = await runtime.run(RunRequest(mode="direct", tool=call()))
    assert state.status == "SUCCESS" and state.final_result == {"value": 42}
    assert state.tool_call_count == 1 and state.llm_call_count == 0
    assert RunState.model_validate_json(state.model_dump_json()) == state
    trace = await runtime.store.get(state.request_id)
    assert trace.state == state
    transitions = [e.data["to"] for e in trace.events if e.kind == "state_transition"]
    assert transitions == ["RUNNING", "WAITING_TOOL", "RUNNING", "SUCCESS"]
    with pytest.raises(ValueError, match="invalid transition"):
        state.transition(Status.RUNNING)


async def test_react_action_observation_and_malformed_recovery(runtime):
    state = await runtime.run(RunRequest(mode="react", mock_script=["bad json", action(), FINAL]))
    assert state.status == "SUCCESS" and state.final_result["value"] == 42
    assert state.llm_call_count == 3
    assert state.errors[0].code == "MALFORMED_LLM_OUTPUT"
    trace = await runtime.store.get(state.request_id)
    assert any(e.kind == "llm_retry" for e in trace.events)
    assert "bad json" not in str([e.data for e in trace.events if e.kind == "llm_error"])


async def test_react_max_steps_and_unresolved_failure(runtime):
    state = await runtime.run(
        RunRequest(mode="react", max_steps=2, mock_script=[action(), action(), FINAL])
    )
    assert state.status == "FAILED" and state.errors[-1].code == "MAX_STEPS"
    failed = await runtime.run(
        RunRequest(mode="react", mock_script=[{"type": "tool", "name": "missing"}, FINAL])
    )
    assert failed.status == "FAILED" and failed.errors[-1].code == "UNRESOLVED_TOOL_ERROR"
    fixed = await runtime.run(
        RunRequest(
            mode="react",
            mock_script=[{"type": "tool", "name": "calculator", "args": {}}, action(), FINAL],
        )
    )
    assert fixed.status == "SUCCESS" and fixed.errors[0].code == "INVALID_ARGUMENTS"


async def test_llm_unavailable_and_explicit_fallback(runtime):
    failed = await runtime.run(RunRequest(mode="react", mock_script=[]))
    assert failed.status == "FAILED" and failed.llm_call_count == 2
    assert all(e.code == "LLM_UNAVAILABLE" for e in failed.errors)
    fallback = await runtime.run(RunRequest(mode="react", mock_script=[], fallback=call()))
    assert fallback.status == "SUCCESS" and fallback.final_result["value"] == 42
    direct = await runtime.run(RunRequest(mode="direct", tool={"name": "missing"}, fallback=call()))
    assert direct.status == "SUCCESS"


async def test_pipeline_refs_parallel_condition_and_skipping(runtime):
    steps = [
        {"id": "a", "tool": call("2+3")},
        {"id": "b", "tool": call("3*3")},
        {
            "id": "sum",
            "depends_on": ["a", "b"],
            "tool": {
                "name": "data_analysis",
                "args": {"values": [{"$ref": "a.value"}, {"$ref": "b.value"}]},
            },
        },
        {
            "id": "yes",
            "depends_on": ["sum"],
            "when": {"ref": "sum.sum", "equals": 14},
            "tool": call("1"),
        },
        {
            "id": "no",
            "depends_on": ["sum"],
            "when": {"ref": "sum.sum", "equals": 0},
            "tool": call("0"),
        },
        {"id": "child", "depends_on": ["no"], "tool": call("2")},
    ]
    state = await runtime.run(RunRequest(mode="pipeline", steps=steps))
    assert state.status == "SUCCESS" and state.tool_call_count == 4
    result = state.final_result["steps"]
    assert result["sum"]["value"]["sum"] == 14
    assert result["yes"]["status"] == "SUCCESS"
    assert result["no"]["status"] == result["child"]["status"] == "SKIPPED"


async def test_partial_failure_optional_and_fallback(runtime):
    steps = [
        {"id": "bad", "tool": {"name": "missing"}},
        {"id": "ok", "tool": call()},
        {"id": "blocked", "depends_on": ["bad"], "tool": call()},
    ]
    state = await runtime.run(RunRequest(mode="pipeline", steps=steps))
    assert state.status == "FAILED"
    assert state.final_result["steps"]["ok"]["value"]["value"] == 42
    assert state.final_result["steps"]["blocked"]["status"] == "BLOCKED"
    state = await runtime.run(
        RunRequest(mode="pipeline", steps=[{**steps[0], "optional": True}, steps[1]])
    )
    assert state.status == "SUCCESS" and state.errors
    state = await runtime.run(RunRequest(mode="pipeline", steps=[{**steps[0], "fallback": call()}]))
    assert state.status == "SUCCESS" and state.final_result["steps"]["bad"]["value"]["value"] == 42


@pytest.mark.parametrize(
    "steps",
    [
        [{"id": "a", "depends_on": ["a"], "tool": call()}],
        [{"id": "a", "depends_on": ["missing"], "tool": call()}],
        [{"id": "a", "tool": call()}, {"id": "a", "tool": call()}],
        [
            {
                "id": "a",
                "tool": {"name": "data_analysis", "args": {"values": [{"$ref": "missing.value"}]}},
            }
        ],
    ],
)
def test_invalid_dag_rejected(steps):
    with pytest.raises(ValidationError):
        RunRequest(mode="pipeline", steps=steps)


async def test_invalid_reference_terminal(runtime):
    state = await runtime.run(
        RunRequest(
            mode="pipeline",
            steps=[
                {"id": "a", "tool": call()},
                {
                    "id": "b",
                    "depends_on": ["a"],
                    "tool": {"name": "data_analysis", "args": {"values": [{"$ref": "a.absent"}]}},
                },
            ],
        )
    )
    assert state.status == "FAILED" and state.errors[-1].code == "INVALID_REFERENCE"


async def test_parallel_real_overlap_and_semaphore(runtime):
    active, peak = 0, 0
    entered = asyncio.Event()

    async def slow(_):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            entered.set()
        try:
            await asyncio.sleep(0.035)
            return {"value": 1}
        finally:
            active -= 1

    runtime.registry.register(Tool("slow", "test", CalcInput, CalcOutput, slow))
    steps = [
        {"id": f"s{i}", "tool": {"name": "slow", "args": {"expression": "1"}}} for i in range(4)
    ]
    parallel = await runtime.run(RunRequest(mode="pipeline", steps=steps, max_parallel=2))
    assert entered.is_set() and peak == 2 and active == 0
    peak = 0
    sequential = await runtime.run(RunRequest(mode="pipeline", steps=steps, parallel=False))
    assert peak == 1 and sequential.latency_ms > parallel.latency_ms * 1.3


async def test_cancel_propagates_and_cleans_children(runtime):
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def slow(_):
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            cleaned.set()

    runtime.registry.register(Tool("slow", "test", CalcInput, CalcOutput, slow, timeout_s=60))
    task = asyncio.create_task(
        runtime.run(
            RunRequest(
                mode="pipeline",
                steps=[{"id": "a", "tool": {"name": "slow", "args": {"expression": "1"}}}],
            )
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    request_id = next(iter(runtime.active))
    assert await runtime.cancel(request_id)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set() and not runtime.active
    trace = await runtime.store.get(request_id)
    assert trace.state.status == "FAILED" and trace.state.errors[-1].code == "CANCELLED"
    assert any(e.kind == "tool_cancelled" for e in trace.events)


async def test_run_timeout_covers_children_and_llm_timeout(runtime):
    state = await runtime.run(
        RunRequest(
            mode="direct", timeout_s=0.025, tool={"name": "http_mock", "args": {"delay_ms": 100}}
        )
    )
    assert state.status == "FAILED" and state.errors[-1].code == "RUN_TIMEOUT"

    class SlowProvider:
        async def complete(self, *args):
            await asyncio.sleep(1)

    runtime.provider = SlowProvider()
    start = time.perf_counter()
    state = await runtime.run(RunRequest(mode="react", llm_timeout_s=0.01))
    assert state.status == "FAILED" and state.errors[-1].code == "LLM_UNAVAILABLE"
    assert time.perf_counter() - start < 1


async def test_concurrent_run_and_trace_isolation(runtime):
    states = await asyncio.gather(
        *[
            runtime.run(RunRequest(mode="direct", tool=call(f"{i}*3"), session_id=f"session-{i}"))
            for i in range(8)
        ]
    )
    assert len({s.request_id for s in states}) == 8
    for i, state in enumerate(states):
        assert state.session_id == f"session-{i}" and state.final_result == {"value": i * 3}
        trace = await runtime.store.get(state.request_id)
        assert [e.seq for e in trace.events] == list(range(len(trace.events)))
        assert len([e for e in trace.events if e.kind == "tool_result"]) == 1


async def test_pipeline_fallback_has_recovering_transition(runtime):
    state = await runtime.run(
        RunRequest(
            mode="pipeline", steps=[{"id": "a", "tool": {"name": "missing"}, "fallback": call()}]
        )
    )
    trace = await runtime.store.get(state.request_id)
    assert state.status == "SUCCESS"
    assert any(e.kind == "state_transition" and e.data["to"] == "RECOVERING" for e in trace.events)
