"""Minimal HTTP and WebSocket API for the Flowgency simulation service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.simulation.geometry import get_network_geometry
from backend.simulation.service import InvalidTransition, SimulationService


class SimulationOptions(BaseModel):
    simulation_speed: float = Field(default=4.0, ge=0.1, le=100.0)


class ResumeOptions(BaseModel):
    simulation_speed: float | None = Field(default=None, ge=0.1, le=100.0)


class SpeedOptions(BaseModel):
    simulation_speed: float = Field(ge=0.1, le=100.0)


def create_app(service: SimulationService | None = None) -> FastAPI:
    simulation = service or SimulationService()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        simulation.open()
        try:
            yield
        finally:
            await asyncio.to_thread(simulation.shutdown)

    app = FastAPI(title="Flowgency API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.simulation_service = simulation

    async def execute(operation: str, *args: object) -> dict[str, object]:
        method = getattr(simulation, operation)
        try:
            return await asyncio.to_thread(method, *args)
        except InvalidTransition as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except (RuntimeError, TimeoutError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/simulation/status")
    async def simulation_status() -> dict[str, object]:
        return simulation.status()

    @app.get("/api/simulation/snapshot")
    async def latest_snapshot() -> dict[str, object]:
        snapshot = simulation.latest_snapshot()
        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no snapshot")
        return snapshot

    @app.get("/api/simulation/network")
    async def network_geometry() -> dict[str, object]:
        return get_network_geometry()

    @app.post("/api/simulation/start")
    async def start(options: SimulationOptions = SimulationOptions()) -> dict[str, object]:
        return await execute("start", options.simulation_speed)

    @app.post("/api/simulation/pause")
    async def pause() -> dict[str, object]:
        return await execute("pause")

    @app.post("/api/simulation/resume")
    async def resume(options: ResumeOptions = ResumeOptions()) -> dict[str, object]:
        return await execute("resume", options.simulation_speed)

    @app.post("/api/simulation/speed")
    async def set_speed(options: SpeedOptions) -> dict[str, object]:
        return await execute("set_speed", options.simulation_speed)

    @app.post("/api/simulation/reset")
    async def reset() -> dict[str, object]:
        return await execute("reset")

    @app.post("/api/simulation/stop")
    async def stop() -> dict[str, object]:
        return await execute("stop")

    @app.websocket("/ws/simulation")
    async def simulation_websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            await websocket.send_json({"type": "status", "data": simulation.status()})
            while True:
                tick_started = asyncio.get_running_loop().time()
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.25)
                except TimeoutError:
                    pass
                snapshot = simulation.latest_snapshot()
                if snapshot is not None:
                    await websocket.send_json({"type": "snapshot", "data": snapshot})
                else:
                    await websocket.send_json({"type": "status", "data": simulation.status()})
                remaining = 0.25 - (asyncio.get_running_loop().time() - tick_started)
                if remaining > 0:
                    await asyncio.sleep(remaining)
        except WebSocketDisconnect:
            return

    return app


app = create_app()
