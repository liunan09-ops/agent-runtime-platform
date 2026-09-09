"""Budgeted, deterministic context preparation with explicit fact annotations."""

import json
import math

from .models import ContextPolicy, ContextState, Message


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 4)


def render_context(context: ContextState) -> str:
    return json.dumps(
        {
            "facts": context.facts,
            "history": context.history_summary,
            "messages": [m.model_dump(exclude={"facts", "important"}) for m in context.messages],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def summarize(value, limit: int = 400) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= limit:
        return text
    return text[: limit - 30] + f"…[summary; {len(text)} chars]"


def compact(messages: list[Message], policy: ContextPolicy) -> ContextState:
    result = ContextState()
    if policy.strategy == "naive":
        result.messages = [
            m.model_copy(deep=True)
            for m in messages[-min(policy.message_budget, policy.recent_window) :]
        ]
    else:
        for message in messages:
            result.facts.update(message.facts)  # Latest explicit fact wins.
        recent = list(range(max(0, len(messages) - policy.recent_window), len(messages)))
        important = [i for i, m in enumerate(messages) if m.important and i not in recent]
        selected = sorted(
            (
                important[-max(0, policy.message_budget - len(recent)) :]
                if policy.message_budget > len(recent)
                else []
            )
            + recent
        )
        selected = selected[-policy.message_budget :]
        for i, message in enumerate(messages):
            if i in selected:
                copy = message.model_copy(deep=True)
                if copy.role == "tool" and len(copy.content) > policy.tool_summary_chars:
                    copy.content = (
                        copy.content[: policy.tool_summary_chars] + "…[tool result compressed]"
                    )
                result.messages.append(copy)
            else:
                result.history_summary.append(f"{message.role}: {message.content[:90]}")
        result.history_summary = result.history_summary[-12:]
    initial_facts = len(result.facts)
    # Hard budget applies to rendered context including metadata, not only content text.
    while estimate_tokens(render_context(result)) > policy.token_budget:
        if result.history_summary:
            result.history_summary.pop(0)
        elif len(result.messages) > 1:
            removable = next((i for i, m in enumerate(result.messages[:-1]) if not m.important), 0)
            result.messages.pop(removable)
        elif result.messages and len(result.messages[0].content) > 40:
            result.messages[0].content = result.messages[0].content[
                -max(40, len(result.messages[0].content) // 2) :
            ]
        elif result.facts:
            result.facts.pop(next(iter(result.facts)))
        elif result.messages:
            result.messages.pop(0)
        else:
            break
    result.dropped_messages = len(messages) - len(result.messages)
    result.dropped_facts = initial_facts - len(result.facts)
    result.estimated_tokens = estimate_tokens(render_context(result))
    return result
