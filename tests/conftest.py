import pytest

from agent_runtime.demo_tools import demo_registry
from agent_runtime.persistence import Store
from agent_runtime.runtime import Runtime


@pytest.fixture
async def runtime(tmp_path):
    store = Store(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await store.initialize()
    runtime = Runtime(demo_registry(), store)
    yield runtime
    await store.close()
