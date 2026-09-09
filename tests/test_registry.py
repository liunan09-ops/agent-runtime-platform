import asyncio
from dataclasses import replace

import pytest

from agent_runtime.demo_tools import CalcInput, CalcOutput, calculate, demo_registry
from agent_runtime.registry import RetryPolicy, Tool, ToolFailure, ToolRegistry


def test_registry_contract_and_lifecycle():
    registry = demo_registry()
    assert len(registry.list()) == 5
    schema = registry.get_schema("calculator")
    assert schema.input_schema["required"] == ["expression"]
    assert "value" in schema.output_contract["properties"]
    assert schema.permission == "read" and schema.idempotent
    assert registry.unregister("calculator")
    assert not registry.unregister("calculator")
    assert registry.get_schema("calculator") is None
    tool = Tool("x", "calc", CalcInput, CalcOutput, calculate)
    registry.register(tool)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(tool)
    with pytest.raises(ValueError, match="async"):
        registry.register(replace(tool, name="sync", execute=lambda _: {}))
    with pytest.raises(ValueError, match="timeout"):
        registry.register(replace(tool, name="bad", timeout_s=0))


@pytest.mark.parametrize(
    "name,args,code",
    [
        ("missing", {}, "UNAVAILABLE_TOOL"),
        ("calculator", {"expression": 42}, "INVALID_ARGUMENTS"),
        ("calculator", {"expression": "1+2", "extra": 1}, "INVALID_ARGUMENTS"),
        ("calculator", {"expression": '__import__("os")'}, "INVALID_EXPRESSION"),
        ("calculator", {"expression": "2**9999999"}, "INVALID_EXPRESSION"),
        ("calculator", {"expression": "1/0"}, "INVALID_EXPRESSION"),
        ("sql_query", {"query": "DELETE FROM inventory"}, "QUERY_REJECTED"),
        ("sql_query", {"query": "ATTACH DATABASE 'x' AS y"}, "QUERY_REJECTED"),
        ("knowledge_lookup", {"key": "../../secrets"}, "NOT_FOUND"),
        ("data_analysis", {"values": []}, "INVALID_ARGUMENTS"),
        ("data_analysis", {"values": ["2"]}, "INVALID_ARGUMENTS"),
        ("http_mock", {"attempt": 9}, "INVALID_ARGUMENTS"),
    ],
)
async def test_rejection_boundaries(name, args, code):
    result = await demo_registry().invoke(name, args)
    assert not result.ok and result.error.code == code


async def test_tool_outputs_and_permission():
    registry = demo_registry()
    assert (await registry.invoke("calculator", {"expression": "(3+4)*2"})).value == {"value": 14}
    assert (
        await registry.invoke(
            "sql_query",
            {"query": "SELECT quantity FROM inventory WHERE item=?", "params": ["widget"]},
        )
    ).value["rows"] == [{"quantity": 12}]
    assert (await registry.invoke("data_analysis", {"values": [2, 4, 9]})).value["sum"] == 15
    assert (
        "runtime"
        in (await registry.invoke("knowledge_lookup", {"key": "runtime"})).value["text"].lower()
    )
    result = await registry.invoke("calculator", {"expression": "1"}, [])
    assert result.error.code == "PERMISSION_DENIED" and result.attempts == 0


async def test_timeout_retry_exception_and_input_isolation():
    registry = demo_registry()
    good, second = await asyncio.gather(
        *[registry.invoke("http_mock", {"scenario": "retry_once"}) for _ in range(2)]
    )
    assert good.ok and second.ok and good.attempts == second.attempts == 2
    exhausted = await registry.invoke("http_mock", {"scenario": "retry_exhausted"})
    assert (
        exhausted.error.code == "RETRY_EXHAUSTED"
        and exhausted.error.details["cause"] == "HTTP_UNAVAILABLE"
    )
    timeout = await registry.invoke("http_mock", {"scenario": "timeout"})
    assert timeout.attempts == 2 and timeout.error.details["cause"] == "TOOL_TIMEOUT"
    exception = await registry.invoke("http_mock", {"scenario": "exception"})
    assert exception.error.code == "TOOL_EXCEPTION" and exception.attempts == 1


async def test_output_contract_and_non_idempotent_not_retried():
    async def bad_output(_):
        return {"unexpected": 1}

    async def transient(_):
        raise ToolFailure("TRANSIENT", "synthetic", retryable=True)

    registry = ToolRegistry()
    registry.register(Tool("bad", "bad", CalcInput, CalcOutput, bad_output))
    registry.register(
        Tool(
            "write",
            "non-idempotent",
            CalcInput,
            CalcOutput,
            transient,
            retry=RetryPolicy(max_attempts=3),
            idempotent=False,
        )
    )
    assert (await registry.invoke("bad", {"expression": "1"})).error.code == "OUTPUT_CONTRACT"
    assert (await registry.invoke("write", {"expression": "1"})).attempts == 1
