from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .models import Error, Model, ToolResult


class RetryPolicy(Model):
    max_attempts: int = Field(default=1, ge=1, le=4)
    backoff_s: float = Field(default=0.01, ge=0, le=2)


class ToolSchema(Model):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_contract: dict[str, Any]
    timeout_s: float
    retry_policy: RetryPolicy
    permission: str
    risk: Literal["low", "medium", "high"]
    idempotent: bool


class ToolFailure(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.error = Error(code=code, message=message, retryable=retryable)
        super().__init__(code)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    execute: Callable[[Any], Awaitable[Any]]
    timeout_s: float = 2
    retry: RetryPolicy | None = None
    permission: str = "read"
    risk: Literal["low", "medium", "high"] = "low"
    idempotent: bool = True

    def schema(self) -> ToolSchema:
        return ToolSchema(name=self.name, description=self.description,
                          input_schema=self.input_model.model_json_schema(),
                          output_contract=self.output_model.model_json_schema(),
                          timeout_s=self.timeout_s, retry_policy=self.retry or RetryPolicy(),
                          permission=self.permission, risk=self.risk, idempotent=self.idempotent)


EventSink = Callable[[str, dict[str, Any]], None]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        if not 0 < tool.timeout_s <= 120:
            raise ValueError("tool timeout outside (0,120]")
        if not asyncio.iscoroutinefunction(tool.execute):
            raise ValueError("execute must be async")
        tool.schema()  # Validate metadata before registration.
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def list(self) -> list[ToolSchema]:
        return [t.schema() for t in self._tools.values()]

    def get_schema(self, name: str) -> ToolSchema | None:
        tool = self._tools.get(name)
        return tool.schema() if tool else None

    async def invoke(self, name: str, args: dict, permissions: list[str] | None = None,
                     emit: EventSink | None = None) -> ToolResult:
        start = time.perf_counter()
        emit = emit or (lambda *_: None)
        tool = self._tools.get(name)
        attempts = 0

        def failure(error: Error) -> ToolResult:
            return ToolResult(ok=False, error=error, attempts=attempts,
                              latency_ms=(time.perf_counter() - start) * 1000)

        if tool is None:
            return failure(Error(code="UNAVAILABLE_TOOL", message="Tool is not registered"))
        if tool.permission not in (permissions if permissions is not None else ["read"]):
            return failure(Error(code="PERMISSION_DENIED", message="Tool permission is not granted"))
        try:
            validated = tool.input_model.model_validate(args)
        except ValidationError as exc:
            return failure(Error(code="INVALID_ARGUMENTS", message="Input schema validation failed",
                                 details={"fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}))
        retry = tool.retry or RetryPolicy()
        allowed = retry.max_attempts if tool.idempotent else 1
        error = Error(code="TOOL_EXCEPTION", message="Tool failed")
        for attempt in range(1, allowed + 1):
            attempts = attempt
            attempt_start = time.perf_counter()
            emit("tool_attempt", {"name": name, "args": args, "attempt": attempt})
            try:
                async with asyncio.timeout(tool.timeout_s):
                    raw = await tool.execute(validated)
                try:
                    value = tool.output_model.model_validate(raw).model_dump(mode="json")
                except ValidationError:
                    error = Error(code="OUTPUT_CONTRACT", message="Tool output violated contract")
                else:
                    emit("attempt_end", {"attempt": attempt, "ok": True,
                                         "latency_ms": (time.perf_counter() - attempt_start) * 1000})
                    return ToolResult(ok=True, value=value, attempts=attempt,
                                      latency_ms=(time.perf_counter() - start) * 1000)
            except TimeoutError:
                error = Error(code="TOOL_TIMEOUT", message="Tool attempt exceeded deadline", retryable=True)
            except asyncio.CancelledError:
                emit("tool_cancelled", {"attempt": attempt})
                raise
            except ToolFailure as exc:
                error = exc.error
            except Exception as exc:
                error = Error(code="TOOL_EXCEPTION", message="Tool raised an exception",
                              details={"exception_type": type(exc).__name__})
            emit("attempt_end", {"attempt": attempt, "ok": False, "error": error.model_dump(mode="json"),
                                 "latency_ms": (time.perf_counter() - attempt_start) * 1000})
            if not error.retryable or attempt == allowed:
                break
            emit("retry", {"attempt": attempt, "next_attempt": attempt + 1, "cause": error.code})
            await asyncio.sleep(retry.backoff_s * attempt)
        if error.retryable and attempts == allowed and allowed > 1:
            error = Error(code="RETRY_EXHAUSTED", message="Tool retry budget exhausted",
                          details={"cause": error.code, "attempts": attempts})
        return failure(error)
