from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import JSON, ForeignKey, Integer, String, event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .models import TERMINAL, Error, RunState, Status, TraceEvent, TraceResponse, utcnow
from .safety import redact


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[dict] = mapped_column(JSON)


class EventRow(Base):
    __tablename__ = "trace_events"
    request_id: Mapped[str] = mapped_column(ForeignKey("runs.request_id"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[dict] = mapped_column(JSON)


class Store:
    """Single-process SQLite persistence. One session per transaction; no shared AsyncSession."""

    def __init__(self, url: str = "sqlite+aiosqlite:///:memory:"):
        if not url.startswith("sqlite+aiosqlite:///"):
            raise ValueError("This demo supports SQLite + aiosqlite only")
        path = url.removeprefix("sqlite+aiosqlite:///")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_async_engine(url, connect_args={"timeout": 10})
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.lock = asyncio.Lock()

        @event.listens_for(self.engine.sync_engine, "connect")
        def configure(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    async def initialize(self, recover_interrupted: bool = False):
        async with self.engine.begin() as con:
            await con.run_sync(Base.metadata.create_all)
        if recover_interrupted:
            async with self.sessions() as session:
                ids = list((await session.scalars(select(RunRow.request_id))).all())
            for request_id in ids:
                trace = await self.get(request_id)
                if trace and trace.state.status not in TERMINAL:
                    old = trace.state.status
                    trace.state.transition(Status.FAILED)
                    trace.state.finished_at = utcnow()
                    trace.state.errors.append(
                        Error(
                            code="INTERRUPTED", message="Previous process ended before completion"
                        )
                    )
                    trace.events.append(
                        TraceEvent(
                            seq=len(trace.events),
                            kind="state_transition",
                            data={"from": old, "to": "FAILED", "cause": "INTERRUPTED"},
                        )
                    )
                    trace.events.append(
                        TraceEvent(
                            seq=len(trace.events),
                            kind="final",
                            data={"result": None, "status": "FAILED"},
                        )
                    )
                    await self.save(trace.state, trace.events)

    async def save(self, state: RunState, events: list[TraceEvent]):
        snapshot = redact(state.model_dump(mode="json"))
        serialized = [redact(e.model_dump(mode="json")) for e in events]
        async with self.lock, self.sessions.begin() as session:
            await session.merge(RunRow(request_id=state.request_id, state=snapshot))
            last = await session.scalar(
                select(func.max(EventRow.seq)).where(EventRow.request_id == state.request_id)
            )
            session.add_all(
                EventRow(request_id=state.request_id, seq=e["seq"], event=e)
                for e in serialized
                if last is None or e["seq"] > last
            )

    async def get(self, request_id: str) -> TraceResponse | None:
        async with self.lock, self.sessions() as session:
            row = await session.get(RunRow, request_id)
            if row is None:
                return None
            events = (
                await session.scalars(
                    select(EventRow).where(EventRow.request_id == request_id).order_by(EventRow.seq)
                )
            ).all()
            return TraceResponse(
                state=RunState.model_validate(row.state),
                events=[TraceEvent.model_validate(e.event) for e in events],
            )

    async def close(self):
        await self.engine.dispose()
