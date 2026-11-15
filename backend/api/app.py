"""Minimal HTTP and WebSocket API for the Flowgency simulation service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictBool

from backend.analytics.runs import save_run
from backend.api.analytics import router as analytics_router
from backend.api.auth import Auth0TokenVerifier, require_permission
from backend.api.replay_assets import ReplayAssetError, ReplayAssetStore, ReplayDatasetRegistry
from backend.insights.gemini import GeminiInsights

from backend.simulation.geometry import get_network_selection_geometry
from backend.simulation.scenarios import (
    DEFAULT_CONTROLLER_MODE,
    DEFAULT_NETWORK,
    DEFAULT_TRAFFIC_PROFILE,
    ScenarioNotFound,
    list_configuration_options,
)
from backend.simulation.service import InvalidTransition, SimulationService
from backend.voice.tts import VoiceSynthesis


class SimulationOptions(BaseModel):
    simulation_speed: float = Field(default=4.0, ge=0.1, le=100.0)
    network: Literal["single_intersection", "london"] = DEFAULT_NETWORK
    traffic_profile: Literal["normal", "rush_hour", "unbalanced"] = DEFAULT_TRAFFIC_PROFILE
    controller_mode: Literal[
        "fixed_timing", "adaptive_network", "adaptive_emergency_priority"
    ] = DEFAULT_CONTROLLER_MODE
    emergency_vehicles_enabled: StrictBool = False


class ResumeOptions(BaseModel):
    simulation_speed: float | None = Field(default=None, ge=0.1, le=100.0)


class SpeedOptions(BaseModel):
    simulation_speed: float = Field(ge=0.1, le=100.0)


def create_app(
    service: SimulationService | None = None,
    auth0_verifier: Auth0TokenVerifier | None = None,
    insights: GeminiInsights | None = None,
    replay_asset_store: ReplayAssetStore | None = None,
    replay_datasets: ReplayDatasetRegistry | None = None,
) -> FastAPI:
    simulation = service or SimulationService(run_sink=save_run)
    speech = VoiceSynthesis()
    replay_assets = replay_asset_store or ReplayAssetStore()
    # demo1 always serves the same bundle as the original single-dataset endpoints.
    replay_registry = replay_datasets or ReplayDatasetRegistry.from_store(replay_assets)

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
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.simulation_service = simulation
    app.state.auth0_verifier = auth0_verifier or Auth0TokenVerifier()
    app.state.insights = insights or GeminiInsights()
    control_permission = Depends(require_permission("simulation:control"))
    replay_permissions = [
        Depends(require_permission("simulation:read")),
        Depends(require_permission("analytics:read")),
        Depends(require_permission("simulation:control")),
    ]
    app.include_router(analytics_router)

    async def execute(operation: str, *args: object) -> dict[str, object]:
        method = getattr(simulation, operation)
        try:
            return await asyncio.to_thread(method, *args)
        except ScenarioNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidTransition as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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

    @app.get("/api/simulation/configuration-options")
    async def supported_configuration() -> dict[str, object]:
        return list_configuration_options()

    @app.get("/api/simulation/network")
    async def network_geometry(network: str | None = None) -> dict[str, object]:
        status_configuration = simulation.status().get("active_configuration") or {}
        selected = network or status_configuration.get("network") or DEFAULT_NETWORK
        try:
            return get_network_selection_geometry(str(selected))
        except (ScenarioNotFound, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/voice/alerts/{event_id}/audio")
    async def voice_audio(event_id: str) -> Response:
        alert = simulation.voice_alert(event_id)
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="voice alert not found")
        try:
            audio = await asyncio.to_thread(speech.render, alert["text"])
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/ai-traffic/manifest", dependencies=replay_permissions)
    async def ai_traffic_manifest() -> dict[str, object]:
        try:
            return await asyncio.to_thread(replay_assets.public_manifest)
        except ReplayAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @app.get("/api/ai-traffic/assets/{asset_id}", dependencies=replay_permissions)
    async def ai_traffic_asset(asset_id: str) -> FileResponse:
        try:
            asset = await asyncio.to_thread(replay_assets.asset, asset_id)
        except ReplayAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return FileResponse(
            asset.path,
            media_type=asset.media_type,
            filename=asset.path.name,
            content_disposition_type="inline",
            headers={"Cache-Control": "private, no-store", "Accept-Ranges": "bytes"},
        )

    @app.get("/api/ai-traffic/datasets", dependencies=replay_permissions)
    async def ai_traffic_datasets() -> dict[str, object]:
        return await asyncio.to_thread(replay_registry.list_datasets)

    @app.get("/api/ai-traffic/datasets/{dataset_id}/manifest", dependencies=replay_permissions)
    async def ai_traffic_dataset_manifest(dataset_id: str) -> dict[str, object]:
        try:
            return await asyncio.to_thread(replay_registry.public_manifest, dataset_id)
        except ReplayAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @app.get(
        "/api/ai-traffic/datasets/{dataset_id}/assets/{asset_id}",
        dependencies=replay_permissions,
    )
    async def ai_traffic_dataset_asset(dataset_id: str, asset_id: str) -> FileResponse:
        try:
            asset = await asyncio.to_thread(replay_registry.asset, dataset_id, asset_id)
        except ReplayAssetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return FileResponse(
            asset.path,
            media_type=asset.media_type,
            filename=asset.path.name,
            content_disposition_type="inline",
            headers={"Cache-Control": "private, no-store", "Accept-Ranges": "bytes"},
        )

    @app.get("/api/voice/audio")
    async def aggregate_voice_audio(
        event_ids: list[str] = Query(min_length=1, max_length=8),
    ) -> Response:
        alert = simulation.aggregate_voice_alerts(event_ids)
        if alert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="voice alerts not found or cannot be aggregated",
            )
        try:
            audio = await asyncio.to_thread(speech.render, alert["text"])
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=300"})

    @app.post("/api/simulation/start", dependencies=[control_permission])
    async def start(options: SimulationOptions = SimulationOptions()) -> dict[str, object]:
        return await execute(
            "start",
            options.simulation_speed,
            options.network,
            options.traffic_profile,
            options.controller_mode,
            options.emergency_vehicles_enabled,
        )

    @app.post("/api/simulation/pause", dependencies=[control_permission])
    async def pause() -> dict[str, object]:
        return await execute("pause")

    @app.post("/api/simulation/resume", dependencies=[control_permission])
    async def resume(options: ResumeOptions = ResumeOptions()) -> dict[str, object]:
        return await execute("resume", options.simulation_speed)

    @app.post("/api/simulation/speed", dependencies=[control_permission])
    async def set_speed(options: SpeedOptions) -> dict[str, object]:
        return await execute("set_speed", options.simulation_speed)

    @app.post("/api/simulation/reset", dependencies=[control_permission])
    async def reset() -> dict[str, object]:
        return await execute("reset")

    @app.post("/api/simulation/stop", dependencies=[control_permission])
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
