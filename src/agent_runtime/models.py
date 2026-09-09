from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Error(Model):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ToolCall(Model):
    name: str = Field(min_length=1, max_length=80)
    args: dict[str, JsonValue] = Field(default_factory=dict)


class ToolResult(Model):
    ok: bool
    value: JsonValue = None
    error: Error | None = None
    attempts: int = 0
    latency_ms: float = 0


class Message(Model):
    role: Literal["user", "assistant", "tool"] = "user"
    content: str = Field(max_length=20000)
    important: bool = False
    facts: dict[str, str] = Field(default_factory=dict)


class ContextPolicy(Model):
    strategy: Literal["naive", "structured"] = "structured"
    message_budget: int = Field(default=8, ge=2, le=100)
    token_budget: int = Field(default=2048, ge=128, le=32000)
    recent_window: int = Field(default=4, ge=1, le=50)
    tool_summary_chars: int = Field(default=400, ge=40, le=4000)


class ContextState(Model):
    messages: list[Message] = Field(default_factory=list)
    facts: dict[str, str] = Field(default_factory=dict)
    history_summary: list[str] = Field(default_factory=list)
    estimated_tokens: int = 0
    dropped_messages: int = 0
    dropped_facts: int = 0
    estimator: str = "ceil(UTF-8 bytes / 4), not provider tokens"


class Condition(Model):
    ref: str
    equals: JsonValue


class Step(Model):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,39}$")
    tool: ToolCall
    depends_on: list[str] = Field(default_factory=list)
    when: Condition | None = None
    fallback: ToolCall | None = None
    optional: bool = False


class RunRequest(Model):
    mode: Literal["direct", "react", "pipeline"]
    user_request: str = Field(default="", max_length=20000)
    session_id: str = Field(default_factory=lambda: str(uuid4()), max_length=100)
    tool: ToolCall | None = None
    steps: list[Step] = Field(default_factory=list, max_length=32)
    parallel: bool = True
    max_parallel: int = Field(default=4, ge=1, le=16)
    max_steps: int = Field(default=8, ge=1, le=30)
    timeout_s: float = Field(default=30, gt=0, le=180)
    llm_timeout_s: float = Field(default=15, gt=0, le=90)
    llm_retries: int = Field(default=1, ge=0, le=3)
    provider: Literal["mock", "deepseek"] = "mock"
    mock_script: list[dict[str, JsonValue] | str] = Field(default_factory=list, max_length=40)
    fallback: ToolCall | None = None
    permissions: list[str] = Field(default_factory=lambda: ["read"], max_length=10)
    messages: list[Message] = Field(default_factory=list, max_length=200)
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)

    @model_validator(mode="after")
    def validate_mode(self) -> RunRequest:
        if self.mode == "direct" and self.tool is None:
            raise ValueError("direct requires tool")
        if self.mode == "pipeline":
            if not self.steps:
                raise ValueError("pipeline requires steps")
            ids = {s.id for s in self.steps}
            if len(ids) != len(self.steps):
                raise ValueError("duplicate step id")
            seen: set[str] = set()
            pending = list(self.steps)
            while pending:
                ready = [s for s in pending if set(s.depends_on) <= seen]
                if not ready:
                    raise ValueError("cyclic or unknown dependency")
                for s in ready:
                    refs = list(find_refs(s.tool.args))
                    if s.fallback:
                        refs += list(find_refs(s.fallback.args))
                    if s.when:
                        refs.append(s.when.ref)
                    if any(r.split(".")[0] not in s.depends_on for r in refs):
                        raise ValueError("references require an explicit dependency")
                    seen.add(s.id)
                    pending.remove(s)
        return self


def find_refs(value: Any):
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"} or not isinstance(value["$ref"], str):
                raise ValueError("reference must be a single string $ref")
            yield value["$ref"]
        else:
            for v in value.values():
                yield from find_refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from find_refs(v)


class Status(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_TOOL = "WAITING_TOOL"
    RECOVERING = "RECOVERING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


TERMINAL = {Status.SUCCESS, Status.FAILED, Status.REJECTED}
TRANSITIONS = {
    Status.PENDING: {Status.RUNNING, Status.REJECTED, Status.FAILED},
    Status.RUNNING: {Status.WAITING_TOOL, Status.RECOVERING, *TERMINAL},
    Status.WAITING_TOOL: {Status.RUNNING, Status.RECOVERING, Status.FAILED},
    Status.RECOVERING: {Status.RUNNING, Status.WAITING_TOOL, *TERMINAL},
}


class HistoryEntry(Model):
    call_id: str
    step: str
    call: ToolCall
    result: ToolResult


class RunState(Model):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    execution_mode: Literal["direct", "react", "pipeline"]
    user_request: str
    status: Status = Status.PENDING
    current_step: int = 0
    tool_history: list[HistoryEntry] = Field(default_factory=list)
    observations: list[JsonValue] = Field(default_factory=list)
    context_state: ContextState = Field(default_factory=ContextState)
    errors: list[Error] = Field(default_factory=list)
    final_result: JsonValue = None
    created_at: str = Field(default_factory=utcnow)
    finished_at: str | None = None
    latency_ms: float = 0
    llm_call_count: int = 0
    tool_call_count: int = 0
    token_usage: dict[str, int] | None = None
    cost_usd: float | None = None
    replay_of: str | None = None

    def transition(self, status: Status) -> None:
        if status not in TRANSITIONS.get(self.status, set()):
            raise ValueError(f"invalid transition {self.status} -> {status}")
        self.status = status


class TraceEvent(Model):
    seq: int
    timestamp: str = Field(default_factory=utcnow)
    kind: str
    step: str | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)


class TraceResponse(Model):
    state: RunState
    events: list[TraceEvent]


class Action(Model):
    type: Literal["tool", "final"]
    name: str | None = None
    args: dict[str, JsonValue] = Field(default_factory=dict)
    result: JsonValue = None

    @model_validator(mode="after")
    def valid_action(self) -> Action:
        if self.type == "tool" and (not self.name or self.result is not None):
            raise ValueError("tool action requires name and no result")
        if self.type == "final" and (self.name is not None or self.args):
            raise ValueError("final action must not have tool name/args")
        return self
