"""Five offline tools. All data are synthetic; no arbitrary code or outbound URL tool."""
import ast
import asyncio
import json
import math
import operator
import sqlite3
from importlib.resources import files
from typing import Literal

import httpx
from pydantic import Field, PrivateAttr, StrictFloat, StrictInt

from .models import Model
from .registry import RetryPolicy, Tool, ToolFailure, ToolRegistry

Number = StrictInt | StrictFloat


class CalcInput(Model):
    expression: str = Field(min_length=1, max_length=200)


class CalcOutput(Model):
    value: float


async def calculate(args: CalcInput):
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Mod: operator.mod}

    def evaluate(node, depth=0):
        if depth > 20:
            raise ValueError("expression depth")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = float(node.value)
        elif isinstance(node, ast.BinOp) and type(node.op) in ops:
            result = ops[type(node.op)](evaluate(node.left, depth + 1), evaluate(node.right, depth + 1))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = evaluate(node.operand, depth + 1) * (-1 if isinstance(node.op, ast.USub) else 1)
        else:
            raise ValueError("unsupported expression")
        if not math.isfinite(result) or abs(result) > 1e15:
            raise ValueError("number outside demo bounds")
        return result

    try:
        return {"value": evaluate(ast.parse(args.expression, mode="eval").body)}
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise ToolFailure("INVALID_EXPRESSION", "Only bounded arithmetic + - * / % is allowed") from exc


class QueryInput(Model):
    query: str = Field(min_length=1, max_length=1000)
    params: list[str | Number] = Field(default_factory=list, max_length=20)


class QueryOutput(Model):
    rows: list[dict]
    row_count: int


def _query(args: QueryInput):
    with sqlite3.connect(":memory:") as con:
        con.execute("CREATE TABLE inventory (item TEXT, quantity INTEGER, price REAL)")
        con.executemany("INSERT INTO inventory VALUES (?, ?, ?)",
                        [("widget", 12, 2.5), ("gadget", 5, 8.0), ("bolt", 30, 0.5)])
        con.execute("PRAGMA query_only=ON")
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
        con.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        ticks = 0

        def budget():
            nonlocal ticks
            ticks += 1
            return int(ticks > 100)

        con.set_progress_handler(budget, 1000)
        con.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in con.execute(args.query, args.params).fetchmany(100)]
        except sqlite3.Error as exc:
            raise ToolFailure("QUERY_REJECTED", "Only bounded read-only SQL on demo inventory is allowed") from exc
        return {"rows": rows, "row_count": len(rows)}


async def query(args: QueryInput):
    return await asyncio.to_thread(_query, args)


class HTTPInput(Model):
    resource: Literal["alpha", "beta", "gamma"] = "alpha"
    delay_ms: int = Field(default=0, ge=0, le=500)
    scenario: Literal["ok", "timeout", "exception", "retry_once", "retry_exhausted"] = "ok"
    _attempt: int = PrivateAttr(default=0)


class HTTPOutput(Model):
    resource: str
    value: int
    source: Literal["httpx.MockTransport"] = "httpx.MockTransport"


async def mock_http(args: HTTPInput):
    args._attempt += 1  # Per invocation input instance; never global shared retry state.
    await asyncio.sleep(0.25 if args.scenario == "timeout" else args.delay_ms / 1000)
    if args.scenario == "exception":
        raise RuntimeError("synthetic tool exception")
    if args.scenario == "retry_exhausted" or (args.scenario == "retry_once" and args._attempt == 1):
        raise ToolFailure("HTTP_UNAVAILABLE", "Synthetic transient upstream failure", retryable=True)

    def handler(request):
        return httpx.Response(200, json={"resource": args.resource,
                                         "value": {"alpha": 10, "beta": 20, "gamma": 30}[args.resource]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await client.get(f"https://demo.invalid/{args.resource}")
        return response.json()


class LookupInput(Model):
    key: str = Field(min_length=1, max_length=80)


class LookupOutput(Model):
    key: str
    text: str
    source: Literal["synthetic-knowledge-v1"] = "synthetic-knowledge-v1"


async def lookup(args: LookupInput):
    data = json.loads(files("agent_runtime").joinpath("data/knowledge.json").read_text())
    if args.key not in data:
        raise ToolFailure("NOT_FOUND", "Knowledge key does not exist")
    return {"key": args.key, "text": data[args.key]}


class AnalysisInput(Model):
    values: list[Number] = Field(min_length=1, max_length=1000)


class AnalysisOutput(Model):
    count: int
    sum: float
    mean: float
    min: float
    max: float


async def analyze(args: AnalysisInput):
    total = math.fsum(args.values)
    return {"count": len(args.values), "sum": total, "mean": total / len(args.values),
            "min": min(args.values), "max": max(args.values)}


def demo_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in [
        Tool("calculator", "Evaluate bounded arithmetic using + - * / % and parentheses.", CalcInput, CalcOutput, calculate),
        Tool("sql_query", "Read-only SQLite inventory(item,quantity,price): widget/12/2.5, gadget/5/8.0, bolt/30/0.5. Max 100 rows.", QueryInput, QueryOutput, query),
        Tool("http_mock", "Offline HTTP fixture: alpha=10, beta=20, gamma=30. Scenario injects deterministic latency/failures.", HTTPInput, HTTPOutput, mock_http, timeout_s=0.12, retry=RetryPolicy(max_attempts=2)),
        Tool("knowledge_lookup", "Read synthetic local knowledge by key: runtime, retry, context, owner, constraint.", LookupInput, LookupOutput, lookup),
        Tool("data_analysis", "Compute count, sum, mean, min and max of a numeric array; no arbitrary Python execution.", AnalysisInput, AnalysisOutput, analyze),
    ]:
        registry.register(tool)
    return registry
