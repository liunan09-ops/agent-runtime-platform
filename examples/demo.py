"""Offline demo without an API server or key: python examples/demo.py."""

import asyncio
import json
from pathlib import Path

from agent_runtime.demo_tools import demo_registry
from agent_runtime.models import RunRequest
from agent_runtime.persistence import Store
from agent_runtime.runtime import Runtime


async def main():
    store = Store("sqlite+aiosqlite:///./runtime-data/demo.db")
    await store.initialize()
    runtime = Runtime(demo_registry(), store)
    try:
        for filename in ("direct.json", "react-offline.json", "pipeline.json"):
            request = RunRequest.model_validate_json(
                await asyncio.to_thread(Path("examples", filename).read_text)
            )
            state = await runtime.run(request)
            print(
                json.dumps(
                    {
                        "example": filename,
                        "status": state.status.value,
                        "result": state.final_result,
                        "request_id": state.request_id,
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
