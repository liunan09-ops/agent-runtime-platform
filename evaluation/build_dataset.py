"""Build v1 fixture once; changing this requires a new dataset version and rerun evidence."""

import hashlib
import json
from pathlib import Path


def call(name, **args):
    return {"name": name, "args": args}


def calc(expr):
    return call("calculator", expression=expr)


def action(tool):
    return {"type": "tool", **tool}


FINAL = {"type": "final", "result": {"$last_observation": True}}
CASES = []


def add(id, request, expected, calls=(), tags=(), kind="run", live=False, live_expected=None):
    CASES.append(
        {
            "id": id,
            "split": "held-out" if int(id[1:]) > 8 else "development",
            "kind": kind,
            "tags": list(tags),
            "request": request,
            "expected": expected,
            "expected_calls": list(calls),
            "live_eligible": live,
            "live_expected": live_expected,
        }
    )


def direct(id, tool, checks, prompt="", **kwargs):
    add(
        id,
        {"mode": "direct", "user_request": prompt, "tool": tool},
        {"status": "SUCCESS", **checks},
        [tool],
        ["direct"],
        **kwargs,
    )


def react(id, script, checks, prompt="", calls=None, **kwargs):
    add(
        id,
        {"mode": "react", "user_request": prompt, "mock_script": script},
        {"status": "SUCCESS", **checks},
        calls
        if calls is not None
        else [
            {k: v for k, v in a.items() if k != "type"}
            for a in script
            if isinstance(a, dict) and a.get("type") == "tool"
        ],
        ["react"],
        **kwargs,
    )


def step(id, tool, **kw):
    return {"id": id, "tool": tool, **kw}


def pipeline(id, steps, expected, calls, **kw):
    add(
        id,
        {"mode": "pipeline", "steps": steps, **kw},
        {"status": "SUCCESS", **expected},
        calls,
        ["pipeline", "workflow"],
    )


direct("d01", calc("2+3*4"), {"final_result.value": 14})
direct("d02", calc("(8-3)/2"), {"final_result.value": 2.5})
direct(
    "d03",
    call("sql_query", query="SELECT quantity FROM inventory WHERE item=?", params=["widget"]),
    {"final_result.rows.0.quantity": 12},
)
direct("d04", call("knowledge_lookup", key="runtime"), {"final_result.key": "runtime"})
direct("d05", call("data_analysis", values=[2, 4, 6]), {"final_result.mean": 4})
direct("d06", call("http_mock", resource="alpha"), {"final_result.value": 10})
add(
    "d07",
    {"mode": "direct", "tool": call("calculator", expression=7)},
    {"status": "REJECTED", "errors.0.code": "INVALID_ARGUMENTS"},
    [call("calculator", expression=7)],
    ["validation"],
)
add(
    "d08",
    {"mode": "direct", "tool": call("missing")},
    {"status": "REJECTED", "errors.0.code": "UNAVAILABLE_TOOL"},
    [call("missing")],
    ["unavailable"],
)
direct(
    "d09",
    calc("13*17"),
    {"final_result.value": 221},
    "Use calculator to compute 13*17. Return its entire output object.",
    live=True,
)
direct(
    "d10",
    call("sql_query", query="SELECT SUM(quantity) AS total FROM inventory"),
    {"final_result.rows.0.total": 47},
    "Use SQL to sum inventory quantity, alias the column total. Return the entire tool output.",
    live=True,
)
direct(
    "d11",
    call("knowledge_lookup", key="owner"),
    {"final_result.text": "Synthetic project owner: Team Atlas."},
    "Look up the owner knowledge key. Return the entire tool output.",
    live=True,
)
direct(
    "d12",
    call("data_analysis", values=[4, 9, 14]),
    {"final_result.mean": 9, "final_result.sum": 27},
    "Analyze [4,9,14] with data_analysis. Return the entire tool output.",
    live=True,
)
react("r01", [action(calc("6*7")), FINAL], {"final_result.value": 42})
react(
    "r02",
    ["not-json", action(calc("3+8")), FINAL],
    {"final_result.value": 11, "errors.0.code": "MALFORMED_LLM_OUTPUT"},
)
react(
    "r03",
    [action(call("calculator")), action(calc("4*4")), FINAL],
    {"final_result.value": 16, "errors.0.code": "INVALID_ARGUMENTS"},
)
react("r04", [action(call("missing")), action(calc("5+7")), FINAL], {"final_result.value": 12})
react(
    "r05",
    [action(call("http_mock", scenario="retry_once")), FINAL],
    {"final_result.value": 10, "tool_call_count": 2},
)
add(
    "r06",
    {"mode": "react", "max_steps": 2, "mock_script": [action(calc("1")), action(calc("2")), FINAL]},
    {"status": "FAILED", "errors.0.code": "MAX_STEPS"},
    [calc("1"), calc("2")],
    ["react", "bounded"],
)
add(
    "r07",
    {"mode": "react", "mock_script": ["bad", "still bad"]},
    {"status": "FAILED", "errors.1.code": "MALFORMED_LLM_OUTPUT"},
    [],
    ["malformed", "failure"],
)
add(
    "r08",
    {"mode": "react", "mock_script": [], "fallback": calc("10+5")},
    {"status": "SUCCESS", "final_result.value": 15, "errors.0.code": "LLM_UNAVAILABLE"},
    [calc("10+5")],
    ["fallback", "recovery"],
)
react(
    "r09",
    [action(calc("7*8")), action(calc("56+9")), FINAL],
    {"final_result.value": 65},
    "First use calculator to compute 7*8. Then use calculator to add 9 to that result. Return the entire final tool output.",
    live=True,
)
react(
    "r10",
    [
        action(call("http_mock", resource="beta")),
        action(call("data_analysis", values=[20, 4, 6])),
        FINAL,
    ],
    {"final_result.sum": 30, "final_result.mean": 10},
    "Fetch beta using http_mock. Then analyze the list [the fetched value,4,6] with data_analysis. Return the entire analysis output.",
    live=True,
)
react(
    "r11",
    [action(call("knowledge_lookup", key="retry")), FINAL],
    {
        "final_result.key": "retry",
        "final_result.text": "Retry only transient failures of idempotent tools within a bounded budget.",
    },
    "Read the retry knowledge key. Return the entire tool output.",
    live=True,
)
react(
    "r12",
    [
        action(
            call("sql_query", query="SELECT price FROM inventory WHERE item=?", params=["gadget"])
        ),
        FINAL,
    ],
    {"final_result.rows.0.price": 8},
    "Use a parameterized SQL query to get the price of gadget from inventory. Return the entire tool output.",
    live=True,
)
pipeline(
    "p01",
    [
        step("a", calc("2+3")),
        step("b", call("data_analysis", values=[{"$ref": "a.value"}, 7]), depends_on=["a"]),
    ],
    {"final_result.steps.b.value.sum": 12},
    [calc("2+3"), call("data_analysis", values=[5, 7])],
    parallel=False,
)
pipeline(
    "p02",
    [
        step("a", call("http_mock", resource="alpha", delay_ms=40)),
        step("b", call("http_mock", resource="beta", delay_ms=40)),
    ],
    {"final_result.steps.b.value.value": 20},
    [
        call("http_mock", resource="alpha", delay_ms=40),
        call("http_mock", resource="beta", delay_ms=40),
    ],
)
pipeline(
    "p03",
    [
        step("a", calc("3")),
        step("b", calc("7"), depends_on=["a"], when={"ref": "a.value", "equals": 3}),
    ],
    {"final_result.steps.b.value.value": 7},
    [calc("3"), calc("7")],
)
pipeline(
    "p04",
    [
        step("a", calc("3")),
        step("b", calc("7"), depends_on=["a"], when={"ref": "a.value", "equals": 0}),
    ],
    {"final_result.steps.b.status": "SKIPPED"},
    [calc("3")],
)
pipeline(
    "p05",
    [step("bad", call("missing")), step("ok", calc("11"))],
    {"status": "FAILED", "final_result.steps.ok.value.value": 11},
    [call("missing"), calc("11")],
)
pipeline(
    "p06",
    [step("bad", call("missing"), optional=True), step("ok", calc("11"))],
    {"final_result.steps.ok.value.value": 11},
    [call("missing"), calc("11")],
)
pipeline(
    "p07",
    [step("a", call("http_mock", scenario="exception"), fallback=calc("9"))],
    {"final_result.steps.a.value.value": 9},
    [call("http_mock", scenario="exception"), calc("9")],
)
pipeline(
    "p08",
    [
        step("a", calc("1")),
        step("b", call("data_analysis", values=[{"$ref": "a.missing"}]), depends_on=["a"]),
    ],
    {"status": "FAILED", "errors.0.code": "INVALID_REFERENCE"},
    [calc("1")],
)
pipeline(
    "p09",
    [
        step("a", calc("12")),
        step("b", calc("18")),
        step(
            "c",
            call("data_analysis", values=[{"$ref": "a.value"}, {"$ref": "b.value"}]),
            depends_on=["a", "b"],
        ),
    ],
    {"final_result.steps.c.value.mean": 15},
    [calc("12"), calc("18"), call("data_analysis", values=[12, 18])],
)
pipeline(
    "p10",
    [
        step("a", call("http_mock", resource="gamma")),
        step("yes", calc("30*2"), depends_on=["a"], when={"ref": "a.value", "equals": 30}),
        step("no", calc("0"), depends_on=["a"], when={"ref": "a.value", "equals": 0}),
    ],
    {"final_result.steps.yes.value.value": 60, "final_result.steps.no.status": "SKIPPED"},
    [call("http_mock", resource="gamma"), calc("30*2")],
)
pipeline(
    "p11",
    [
        step("bad", call("http_mock", scenario="retry_exhausted")),
        step("child", calc("1"), depends_on=["bad"]),
        step("ok", calc("4")),
    ],
    {
        "status": "FAILED",
        "final_result.steps.child.status": "BLOCKED",
        "final_result.steps.ok.value.value": 4,
    },
    [call("http_mock", scenario="retry_exhausted"), calc("4")],
)
pipeline(
    "p12",
    [
        step(
            "a", call("http_mock", scenario="timeout"), fallback=call("http_mock", resource="gamma")
        )
    ],
    {"final_result.steps.a.value.value": 30},
    [call("http_mock", scenario="timeout"), call("http_mock", resource="gamma")],
)
for i, turns in enumerate((5, 10, 20, 40)):
    for j, strategy in enumerate(("naive", "structured")):
        add(
            f"e{i * 2 + j + 1:02}",
            {"turns": turns, "strategy": strategy, "token_budget": 400},
            {"required_facts": 4},
            tags=["context", "retention"],
            kind="context",
        )
add(
    "e09",
    {"mode": "direct", "tool": calc("9*9")},
    {"status": "SUCCESS", "final_result.value": 81},
    [calc("9*9")],
    ["replay"],
    kind="replay",
)
add(
    "e10",
    {"mode": "direct", "tool": call("http_mock", scenario="exception")},
    {"status": "FAILED", "errors.0.code": "TOOL_EXCEPTION"},
    [call("http_mock", scenario="exception")],
    ["replay", "failure"],
    kind="replay",
)
add(
    "e11",
    {"mode": "direct", "tool": call("http_mock", scenario="timeout")},
    {
        "status": "FAILED",
        "errors.0.code": "RETRY_EXHAUSTED",
        "errors.0.details.cause": "TOOL_TIMEOUT",
    },
    [call("http_mock", scenario="timeout")],
    ["timeout", "retry"],
)
add(
    "e12",
    {"mode": "direct", "tool": calc("1"), "permissions": []},
    {"status": "REJECTED", "errors.0.code": "PERMISSION_DENIED"},
    [calc("1")],
    ["permission"],
)

if __name__ == "__main__":
    path = Path("evaluation/datasets/tasks-v1.json")
    if path.exists():
        raise SystemExit("Dataset already exists; create a new version instead of overwriting")
    payload = {
        "version": "1.0.0",
        "created_at": "2026-09-09",
        "data_source": "synthetic project-owned fixtures",
        "cases": CASES,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "version": "1.0.0",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "count": len(CASES),
        "development": sum(c["split"] == "development" for c in CASES),
        "held_out": sum(c["split"] == "held-out" for c in CASES),
        "live_eligible": sum(c["live_eligible"] for c in CASES),
        "policy": "Frozen before held-out runs; no runtime imports from evaluation; no special held-out rules.",
    }
    Path("evaluation/datasets/manifest-v1.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(manifest)
