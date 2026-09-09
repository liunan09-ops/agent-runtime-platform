"""Best-effort trace redaction, not a general personal-data detector."""

import os
import re
from typing import Any

SENSITIVE = re.compile(
    r"api.?key|authorization|password|secret|access.?token|reasoning_content|chain.of.thought", re.I
)
TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b|Bearer\s+[^\s\"']+", re.I)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]" if SENSITIVE.search(str(k)) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            secret = os.getenv(key)
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return TOKEN.sub("[REDACTED]", value)
    return value
