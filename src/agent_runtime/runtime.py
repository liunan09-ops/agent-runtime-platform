from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from uuid import uuid4

from pydantic import ValidationError

from .context import compact, summarize
from .models import (
    TERMINAL,
    Error,
    HistoryEntry,
    Message,
    RunRequest,
    RunState,
    Status,
    ToolCall,
    ToolResult,
    TraceEvent,
    TraceResponse,
    utcnow,
)
from .persistence import Store
from .providers import CompatibleProvider, MockProvider, Provider, ProviderError, parse_action
from .registry import ToolRegistry
from .safety import redact


@dataclass
class Execution:
    request: RunRequest
    state: RunState
    events: list[TraceEvent] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)

    def emit(self, kind: str, data: dict, step: str | None = None):
        self.events.append(TraceEvent(seq=len(self.events), kind=kind, step=step, data=redact(data)))


class Runtime:
    def __init__(self, registry: ToolRegistry, store: Store, provider: Provider | None = None):
        self.registry, self.store, self.provider = registry, store, provider
        self.active: dict[str, asyncio.Task] = {}

    async def _transition(self, run: Execution, status: Status):
        old = run.state.status
        run.state.transition(status)
        run.emit("state_transition", {"from": old.value, "to": status.value})
        await self.store.save(run.state, run.events)

    def _context(self, run: Execution):
        run.state.context_state = compact(run.messages, run.request.context_policy)
        run.emit("context", {"estimated_tokens": run.state.context_state.estimated_tokens,
                             "messages": len(run.state.context_state.messages),
                             "facts": len(run.state.context_state.facts),
                             "dropped_facts": run.state.context_state.dropped_facts})

    async def run(self, request: RunRequest) -> RunState:
        state = RunState(session_id=request.session_id, execution_mode=request.mode,
                         user_request=request.user_request)
        run = Execution(request, state, messages=[m.model_copy(deep=True) for m in request.messages])
        run.messages.append(Message(content=request.user_request, important=True))
        run.emit("request", {"request": request.model_dump(mode="json"), "mode": request.mode})
        self._context(run)
        start = time.perf_counter()
        await self.store.save(state, run.events)
        task = asyncio.current_task()
        if task:
            self.active[state.request_id] = task
        cancelled = False
        try:
            async with asyncio.timeout(request.timeout_s):
                await self._transition(run, Status.RUNNING)
                if request.mode == "direct":
                    await self._direct(run, request.tool)
                elif request.mode == "react":
                    await self._react(run)
                else:
                    await self._pipeline(run)
        except TimeoutError:
            state.errors.append(Error(code="RUN_TIMEOUT", message="Run exceeded total deadline"))
            if state.status not in TERMINAL:
                await self._transition(run, Status.FAILED)
        except asyncio.CancelledError:
            cancelled = True
            state.errors.append(Error(code="CANCELLED", message="Run was cancelled; child tasks cleaned up"))
            if state.status not in TERMINAL:
                await self._transition(run, Status.FAILED)
        except Exception as exc:
            state.errors.append(Error(code="RUNTIME_ERROR", message="Runtime execution failed",
                                      details={"exception_type": type(exc).__name__}))
            if state.status not in TERMINAL:
                await self._transition(run, Status.FAILED)
        finally:
            state.finished_at = utcnow()
            state.latency_ms = (time.perf_counter() - start) * 1000
            run.emit("final", {"result": state.final_result, "status": state.status.value,
                               "latency_ms": state.latency_ms})
            await self.store.save(state, run.events)
            self.active.pop(state.request_id, None)
        if cancelled:
            raise asyncio.CancelledError
        # Apply same redaction to caller-visible state as persisted trace.
        return RunState.model_validate(redact(state.model_dump(mode="json")))

    async def cancel(self, request_id: str) -> bool:
        task = self.active.get(request_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def _call(self, run: Execution, call: ToolCall, step: str) -> ToolResult:
        call_id = str(uuid4())
        run.emit("tool_selected", {"call_id": call_id, "name": call.name, "args": call.args}, step)

        def emit(kind, data):
            if kind == "tool_attempt":
                run.state.tool_call_count += 1
            run.emit(kind, {"call_id": call_id, **data}, step)

        result = await self.registry.invoke(call.name, call.args, run.request.permissions, emit)
        entry = HistoryEntry(call_id=call_id, step=step, call=call, result=result)
        run.state.tool_history.append(entry)
        observation = {"name": call.name, **result.model_dump(mode="json")}
        run.state.observations.append(observation)
        run.messages.append(Message(role="tool", content=json.dumps(observation, ensure_ascii=False)))
        if result.error:
            run.state.errors.append(result.error)
        run.emit("tool_result", {"call_id": call_id, "name": call.name, "args": call.args,
                                 "result": result.model_dump(mode="json"),
                                 "summary": summarize(result.value)}, step)
        return result

    async def _after_tools(self, run: Execution, results: list[ToolResult]):
        if any(not r.ok or r.attempts > 1 for r in results):
            await self._transition(run, Status.RECOVERING)
        await self._transition(run, Status.RUNNING)
        self._context(run)

    async def _direct(self, run: Execution, call: ToolCall):
        run.state.current_step += 1
        await self._transition(run, Status.WAITING_TOOL)
        result = await self._call(run, call, "direct")
        await self._after_tools(run, [result])
        if not result.ok and run.request.fallback and run.request.fallback != call:
            await self._transition(run, Status.RECOVERING)
            run.emit("fallback", {"tool": run.request.fallback.name})
            await self._transition(run, Status.WAITING_TOOL)
            result = await self._call(run, run.request.fallback, "fallback")
            await self._after_tools(run, [result])
        run.state.final_result = result.value
        rejected = result.error and result.error.code in {"INVALID_ARGUMENTS", "UNAVAILABLE_TOOL", "PERMISSION_DENIED"}
        await self._transition(run, Status.SUCCESS if result.ok else Status.REJECTED if rejected else Status.FAILED)

    async def _react(self, run: Execution):
        provider = self.provider or (MockProvider(run.request.mock_script) if run.request.provider == "mock" else CompatibleProvider())
        schemas = [s.model_dump(mode="json") for s in self.registry.list() if s.permission in run.request.permissions]
        unresolved_error = False
        for step in range(1, run.request.max_steps + 1):
            run.state.current_step = step
            action = None
            for attempt in range(1, run.request.llm_retries + 2):
                self._context(run)
                start = time.perf_counter()
                run.state.llm_call_count += 1
                run.emit("llm_start", {"provider": run.request.provider, "attempt": attempt}, str(step))
                try:
                    async with asyncio.timeout(run.request.llm_timeout_s):
                        completion = await provider.complete(run.state.context_state, schemas, run.state.observations)
                    if completion.usage:
                        run.state.token_usage = run.state.token_usage or {}
                        for key, value in completion.usage.items():
                            run.state.token_usage[key] = run.state.token_usage.get(key, 0) + value
                    run.emit("llm_call", {"metadata": completion.metadata, "usage": completion.usage,
                                          "attempt": attempt, "latency_ms": (time.perf_counter() - start) * 1000}, str(step))
                    action = parse_action(completion.content)
                    run.emit("action", action.model_dump(mode="json"), str(step))
                    break
                except (ValidationError, ValueError):
                    error = Error(code="MALFORMED_LLM_OUTPUT", message="Expected a JSON tool or final action", retryable=True)
                except (ProviderError, TimeoutError):
                    error = Error(code="LLM_UNAVAILABLE", message="LLM unavailable or timed out", retryable=True)
                run.state.errors.append(error)
                run.emit("llm_error", {"error": error.model_dump(mode="json"), "attempt": attempt,
                                       "latency_ms": (time.perf_counter() - start) * 1000}, str(step))
                await self._transition(run, Status.RECOVERING)
                run.messages.append(Message(role="user", content="Runtime feedback: " + error.code + ". Return a valid JSON action."))
                if attempt <= run.request.llm_retries:
                    run.emit("llm_retry", {"attempt": attempt, "cause": error.code}, str(step))
                    await self._transition(run, Status.RUNNING)
            if action is None:
                if run.request.fallback:
                    run.emit("fallback", {"tool": run.request.fallback.name, "cause": "LLM_FAILURE"})
                    await self._direct(run, run.request.fallback)
                else:
                    await self._transition(run, Status.FAILED)
                return
            if action.type == "final":
                if unresolved_error:
                    run.state.errors.append(Error(code="UNRESOLVED_TOOL_ERROR", message="Cannot complete after unresolved tool failure"))
                    await self._transition(run, Status.FAILED)
                else:
                    run.state.final_result = action.result
                    await self._transition(run, Status.SUCCESS)
                return
            await self._transition(run, Status.WAITING_TOOL)
            result = await self._call(run, ToolCall(name=action.name, args=action.args), str(step))
            unresolved_error = not result.ok
            await self._after_tools(run, [result])
        run.state.errors.append(Error(code="MAX_STEPS", message="ReAct step budget exhausted"))
        await self._transition(run, Status.FAILED)

    async def _pipeline(self, run: Execution):
        remaining = list(run.request.steps)
        values, outputs = {}, {}
        failed_required = False
        semaphore = asyncio.Semaphore(run.request.max_parallel)

        async def execute_step(step):
            async with semaphore:
                try:
                    args = resolve(step.tool.args, values)
                    result = await self._call(run, ToolCall(name=step.tool.name, args=args), step.id)
                    if not result.ok and step.fallback:
                        run.emit("fallback", {"tool": step.fallback.name}, step.id)
                        fallback = ToolCall(name=step.fallback.name, args=resolve(step.fallback.args, values))
                        result = await self._call(run, fallback, step.id + ":fallback")
                    return result
                except (KeyError, TypeError, IndexError, ValueError):
                    error = Error(code="INVALID_REFERENCE", message="Pipeline reference could not be resolved")
                    run.state.errors.append(error)
                    return ToolResult(ok=False, error=error)

        while remaining:
            ready = [s for s in remaining if set(s.depends_on) <= outputs.keys()]
            if not ready:
                raise ValueError("unresolvable DAG")  # Defense in depth after request validation.
            runnable = []
            for step in ready:
                remaining.remove(step)
                run.state.current_step += 1
                blocked = any(outputs[d]["status"] in {"FAILED", "BLOCKED"} for d in step.depends_on)
                skipped = any(outputs[d]["status"] == "SKIPPED" for d in step.depends_on)
                try:
                    condition = step.when is None or lookup_ref(step.when.ref, values) == step.when.equals
                except (KeyError, TypeError, IndexError, ValueError):
                    condition = False
                    if not blocked and not skipped:
                        blocked = True
                        run.state.errors.append(Error(code="INVALID_REFERENCE", message="Condition reference is missing"))
                if blocked or skipped or not condition:
                    outputs[step.id] = {"status": "BLOCKED" if blocked else "SKIPPED", "value": None}
                    run.emit("step_skipped", {"status": outputs[step.id]["status"]}, step.id)
                    failed_required |= blocked and not step.optional
                else:
                    runnable.append(step)
            if not runnable:
                continue
            await self._transition(run, Status.WAITING_TOOL)
            if run.request.parallel:
                async with asyncio.TaskGroup() as group:
                    tasks = [group.create_task(execute_step(s)) for s in runnable]
                results = [t.result() for t in tasks]
            else:
                results = [await execute_step(s) for s in runnable]
            for step, result in zip(runnable, results, strict=True):
                outputs[step.id] = {"status": "SUCCESS" if result.ok else "FAILED", "value": result.value,
                                    "error": result.error.model_dump(mode="json") if result.error else None}
                if result.ok:
                    values[step.id] = result.value
                failed_required |= not result.ok and not step.optional
            # Keep completed siblings visible even if a later layer times out or is cancelled.
            run.state.final_result = {"steps": dict(outputs)}
            await self._after_tools(run, results)
        run.state.final_result = {"steps": outputs}
        await self._transition(run, Status.FAILED if failed_required else Status.SUCCESS)

    async def replay(self, request_id: str) -> TraceResponse:
        original = await self.store.get(request_id)
        if original is None:
            raise KeyError(request_id)
        if original.state.status not in TERMINAL:
            raise ValueError("Only terminal runs can be replayed")
        start = time.perf_counter()
        state = original.state.model_copy(deep=True)
        state.request_id, state.replay_of = str(uuid4()), request_id
        state.created_at, state.finished_at = utcnow(), utcnow()
        state.llm_call_count, state.tool_call_count, state.token_usage, state.cost_usd = 0, 0, None, None
        events = [TraceEvent(seq=0, kind="replay", data={"source_request_id": request_id,
                            "strategy": "saved-results-v1", "source_status": original.state.status.value})]
        for history in state.tool_history:
            events.append(TraceEvent(seq=len(events), kind="replayed_tool_result", step=history.step,
                                     data={"name": history.call.name, "args": history.call.args,
                                           "result": history.result.model_dump(mode="json")}))
        state.latency_ms = (time.perf_counter() - start) * 1000
        events.append(TraceEvent(seq=len(events), kind="final", data={"result": state.final_result, "status": state.status.value}))
        await self.store.save(state, events)
        return TraceResponse(state=state, events=events)


def lookup_ref(ref: str, values):
    value = values
    for part in ref.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def resolve(value, values):
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            return lookup_ref(value["$ref"], values)
        return {k: resolve(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, values) for v in value]
    return value
