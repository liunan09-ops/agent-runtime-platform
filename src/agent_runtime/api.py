import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from . import __version__
from .demo_tools import demo_registry
from .models import Model, RunRequest, RunState, TraceResponse
from .persistence import Store
from .registry import ToolSchema
from .runtime import Runtime


class Health(Model):
    status: str
    version: str
    storage: str


class CancelResponse(Model):
    request_id: str
    cancellation_requested: bool


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(
            database_url
            or os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./runtime-data/runtime.db")
        )
        await store.initialize(recover_interrupted=True)
        runtime = Runtime(demo_registry(), store)
        app.state.runtime = runtime
        try:
            yield
        finally:
            tasks = list(runtime.active.values())
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await store.close()

    app = FastAPI(
        title="Agent Runtime & Tool Workflow Platform", version=__version__, lifespan=lifespan
    )

    @app.get("/health", response_model=Health)
    async def health():
        # Probe actual persistence connection, not only process liveness.
        from sqlalchemy import text

        async with app.state.runtime.store.engine.connect() as con:
            await con.execute(text("SELECT 1"))
        return Health(status="ok", version=__version__, storage="sqlite")

    @app.get("/tools", response_model=list[ToolSchema])
    async def tools():
        return app.state.runtime.registry.list()

    @app.post("/runs", response_model=RunState)
    async def run(request: RunRequest):
        return await app.state.runtime.run(request)

    @app.get("/runs/{request_id}", response_model=RunState)
    async def get_run(request_id: str):
        return (await get_trace(request_id)).state

    @app.get("/traces/{request_id}", response_model=TraceResponse)
    async def get_trace(request_id: str):
        trace = await app.state.runtime.store.get(request_id)
        if trace is None:
            raise HTTPException(404, "Run not found")
        return trace

    @app.post("/replay/{request_id}", response_model=TraceResponse)
    async def replay(request_id: str):
        try:
            return await app.state.runtime.replay(request_id)
        except KeyError:
            raise HTTPException(404, "Run not found") from None
        except ValueError:
            raise HTTPException(409, "Run is not terminal") from None

    @app.delete("/runs/{request_id}", response_model=CancelResponse)
    async def cancel(request_id: str):
        cancelled = await app.state.runtime.cancel(request_id)
        if not cancelled:
            raise HTTPException(409, "Run is not active in this process")
        return CancelResponse(request_id=request_id, cancellation_requested=True)

    return app


app = create_app()
