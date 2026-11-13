"""Single-worker lifecycle service around :class:`SumoRunner`."""

from __future__ import annotations

import copy
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable
from uuid import uuid4

from .runner import SumoRunner


class SimulationState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    ERROR = "error"


class InvalidTransition(RuntimeError):
    """Raised when a lifecycle operation is invalid for the current state."""


@dataclass
class _Command:
    name: str
    future: Future[dict[str, Any] | None]
    speed: float | None = None
    control_mode: str | None = None


RunnerFactory = Callable[[], SumoRunner]


class SimulationService:
    """Serialize all TraCI access onto one dedicated worker thread."""

    def __init__(
        self,
        runner_factory: RunnerFactory | None = None,
        *,
        default_speed: float = 4.0,
        command_timeout_s: float = 10.0,
    ) -> None:
        self._runner_factory = runner_factory or self._default_runner_factory
        self._default_speed = self._validate_speed(default_speed)
        self._speed = self._default_speed
        self._control_mode = "fixed"
        self._command_timeout_s = command_timeout_s
        self._commands: queue.Queue[_Command] = queue.Queue()
        self._lock = threading.Lock()
        self._state = SimulationState.IDLE
        self._latest_snapshot: dict[str, Any] | None = None
        self._error: str | None = None
        self._worker: threading.Thread | None = None
        self._worker_started = threading.Event()

    @staticmethod
    def _default_runner_factory() -> SumoRunner:
        return SumoRunner(run_id=f"service-{uuid4()}")

    @staticmethod
    def _validate_speed(speed: float) -> float:
        speed = float(speed)
        if not 0.1 <= speed <= 100.0:
            raise ValueError("simulation speed must be between 0.1 and 100.0")
        return speed

    def open(self) -> None:
        """Start the command worker without starting SUMO."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker_started.clear()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="flowgency-sumo-worker",
            daemon=True,
        )
        self._worker.start()
        if not self._worker_started.wait(self._command_timeout_s):
            raise RuntimeError("simulation worker did not start")

    def start(self, speed: float | None = None, control_mode: str = "fixed") -> dict[str, Any]:
        selected_speed = self._default_speed if speed is None else self._validate_speed(speed)
        if control_mode not in {"fixed", "adaptive"}:
            raise ValueError("control_mode must be fixed or adaptive")
        return self._submit("start", speed=selected_speed, control_mode=control_mode)

    def pause(self) -> dict[str, Any]:
        return self._submit("pause")

    def resume(self, speed: float | None = None) -> dict[str, Any]:
        validated = None if speed is None else self._validate_speed(speed)
        return self._submit("resume", speed=validated)

    def set_speed(self, speed: float) -> dict[str, Any]:
        """Change pacing without advancing or restarting the SUMO runner."""
        return self._submit("set_speed", speed=self._validate_speed(speed))

    def reset(self) -> dict[str, Any]:
        return self._submit("reset")

    def stop(self) -> dict[str, Any]:
        return self._submit("stop")

    def shutdown(self) -> None:
        """Stop SUMO, terminate the worker, and wait for clean process ownership release."""
        worker = self._worker
        if worker is None or not worker.is_alive():
            return
        self._submit("shutdown")
        worker.join(self._command_timeout_s)
        if worker.is_alive():
            raise RuntimeError("simulation worker did not shut down")
        self._worker = None

    def status(self) -> dict[str, Any]:
        """Return a thread-safe status copy; this never calls TraCI."""
        with self._lock:
            snapshot = self._latest_snapshot
            return {
                "state": self._state.value,
                "simulation_speed": self._speed,
                "control_mode": self._control_mode,
                "simulation_time_s": (
                    snapshot["simulation_time_s"] if snapshot is not None else None
                ),
                "has_snapshot": snapshot is not None,
                "error": self._error,
            }

    def latest_snapshot(self) -> dict[str, Any] | None:
        """Return a deep copy so clients cannot mutate shared worker state."""
        with self._lock:
            return copy.deepcopy(self._latest_snapshot)

    def _submit(
        self, name: str, speed: float | None = None, control_mode: str | None = None
    ) -> dict[str, Any]:
        worker = self._worker
        if worker is None or not worker.is_alive():
            raise RuntimeError("simulation service is not open")
        future: Future[dict[str, Any] | None] = Future()
        self._commands.put(_Command(name=name, future=future, speed=speed, control_mode=control_mode))
        result = future.result(timeout=self._command_timeout_s)
        return result or self.status()

    def _set_state(
        self,
        state: SimulationState,
        *,
        snapshot: dict[str, Any] | None | object = ...,
        error: str | None | object = ...,
    ) -> None:
        with self._lock:
            self._state = state
            if snapshot is not ...:
                self._latest_snapshot = snapshot  # type: ignore[assignment]
            if error is not ...:
                self._error = error  # type: ignore[assignment]

    def _current_state(self) -> SimulationState:
        with self._lock:
            return self._state

    def _worker_loop(self) -> None:
        runner: SumoRunner | None = None
        self._worker_started.set()
        keep_running = True
        while keep_running:
            try:
                if self._current_state() is SimulationState.RUNNING:
                    timeout = 1.0 / self._speed
                    try:
                        command = self._commands.get(timeout=timeout)
                    except queue.Empty:
                        if runner is None:
                            raise RuntimeError("running state has no SUMO runner")
                        runner.advance()
                        snapshot = runner.extract_snapshot()
                        self._set_state(SimulationState.RUNNING, snapshot=snapshot)
                        if not runner.has_pending_vehicles():
                            runner.close()
                            runner = None
                            self._set_state(SimulationState.FINISHED)
                        continue
                else:
                    command = self._commands.get()

                try:
                    runner, keep_running = self._handle_command(command, runner)
                    if not command.future.done():
                        command.future.set_result(self.status())
                except BaseException as exc:
                    if not command.future.done():
                        command.future.set_exception(exc)
                    if not isinstance(exc, (InvalidTransition, ValueError)):
                        if runner is not None:
                            runner.close()
                            runner = None
                        self._set_state(SimulationState.ERROR, error=str(exc))
            except BaseException as exc:
                if runner is not None:
                    try:
                        runner.close()
                    finally:
                        runner = None
                self._set_state(SimulationState.ERROR, error=str(exc))

        if runner is not None:
            runner.close()

    def _handle_command(
        self, command: _Command, runner: SumoRunner | None
    ) -> tuple[SumoRunner | None, bool]:
        state = self._current_state()

        if command.name == "start":
            if state is not SimulationState.IDLE:
                raise InvalidTransition(f"cannot start simulation while {state.value}")
            runner = self._runner_factory()
            try:
                if command.control_mode == "adaptive":
                    runner.configure_control_mode("adaptive")
                runner.start()
                snapshot = runner.extract_snapshot()
            except BaseException:
                runner.close()
                raise
            self._speed = command.speed or self._default_speed
            self._control_mode = command.control_mode or "fixed"
            self._set_state(SimulationState.RUNNING, snapshot=snapshot, error=None)
            return runner, True

        if command.name == "pause":
            if state is not SimulationState.RUNNING:
                raise InvalidTransition(f"cannot pause simulation while {state.value}")
            self._set_state(SimulationState.PAUSED)
            return runner, True

        if command.name == "resume":
            if state is not SimulationState.PAUSED:
                raise InvalidTransition(f"cannot resume simulation while {state.value}")
            if command.speed is not None:
                self._speed = command.speed
            self._set_state(SimulationState.RUNNING)
            return runner, True

        if command.name == "set_speed":
            if state not in (SimulationState.RUNNING, SimulationState.PAUSED):
                raise InvalidTransition(f"cannot change speed while {state.value}")
            if command.speed is None:  # defensive; public API always supplies it
                raise ValueError("simulation speed is required")
            self._speed = command.speed
            return runner, True

        if command.name == "reset":
            if state is SimulationState.IDLE:
                raise InvalidTransition("cannot reset an idle simulation")
            if runner is not None:
                runner.close()
            runner = self._runner_factory()
            try:
                if self._control_mode == "adaptive":
                    runner.configure_control_mode("adaptive")
                runner.start()
                snapshot = runner.extract_snapshot()
            except BaseException:
                runner.close()
                raise
            self._speed = self._default_speed
            self._set_state(SimulationState.PAUSED, snapshot=snapshot, error=None)
            return runner, True

        if command.name == "stop":
            if state is SimulationState.IDLE:
                raise InvalidTransition("cannot stop an idle simulation")
            if runner is not None:
                runner.close()
                runner = None
            self._speed = self._default_speed
            self._control_mode = "fixed"
            self._set_state(SimulationState.IDLE, snapshot=None, error=None)
            return runner, True

        if command.name == "shutdown":
            if runner is not None:
                runner.close()
                runner = None
            self._speed = self._default_speed
            self._control_mode = "fixed"
            self._set_state(SimulationState.IDLE, snapshot=None, error=None)
            return runner, False

        raise ValueError(f"unknown simulation command: {command.name}")
