from agent_runtime.models import Message


def long_context(turns: int) -> list[Message]:
    messages = []
    for i in range(turns):
        facts = (
            {"owner": "Atlas", "budget": "250"}
            if i == 0
            else {"region": "East"}
            if i == turns - 2
            else {"deadline": "Friday"}
            if i == turns - 1
            else {}
        )
        content = (
            "; ".join(f"{k}={v}" for k, v in facts.items())
            or f"Synthetic progress update {i}: " + "routine discussion " * 25
        )
        messages.append(Message(content=content, facts=facts, important=bool(facts)))
        messages.append(
            Message(role="assistant", content=f"Acknowledged turn {i}; " + "routine response " * 12)
        )
    return messages


FACTS = {"owner": "Atlas", "budget": "250", "region": "East", "deadline": "Friday"}
