"""uvicorn's multi-worker supervisor with rolling, one-at-a-time worker recycling.

Stock uvicorn lets each worker exit by itself after ``--limit-max-requests``
and only then starts a replacement, which needs seconds to import the app; the
supervisor also blocks up to ``--timeout-worker-healthcheck`` pinging that
not-yet-started replacement before it notices another dead worker.  With two
workers on similar request counts both are regularly absent together and the
whole site stops answering.  Here the supervisor owns the request limit
instead: workers never exit on it, and a worker over its limit is retired only
after its replacement is serving, one worker at a time, so the listening
socket always has a ready worker behind it.

Run as ``python -c "...; from app.worker_supervisor import main; main()" <uvicorn args>``.
"""

from __future__ import annotations
from typing import Any

import asyncio
import random
import time

import importlib

from .core.invariants import InternalInvariantError

from uvicorn.config import STARTUP_FAILURE, Config
from uvicorn.protocols.http.h11_impl import H11Protocol
from uvicorn.server import Server
from uvicorn.supervisors.multiprocess import Multiprocess, Process, logger


class _DrainingH11Protocol(H11Protocol):
    _first_request_grace = 0.25
    _drain_timer: asyncio.TimerHandle | None = None

    def shutdown(self) -> None:
        if self.cycle is not None:
            super().shutdown()
            return
        # An accepted socket may still be waiting for its first request headers.
        # Keep this wait inside Server.shutdown's existing graceful timeout.
        if self._drain_timer is None:
            timeout = self.config.timeout_graceful_shutdown
            grace = self._first_request_grace if timeout is None else min(self._first_request_grace, timeout)
            self._drain_timer = self.loop.call_later(grace, super().shutdown)

    def handle_events(self) -> None:
        super().handle_events()
        if self._drain_timer is not None and self.cycle is not None:
            self._drain_timer.cancel()
            super().shutdown()

    def connection_lost(self, exc: Exception | None) -> None:
        if self._drain_timer is not None:
            self._drain_timer.cancel()
        super().connection_lost(exc)


class _WorkerServer(Server):
    async def startup(self, sockets: list[Any] | None = None) -> None:
        if self.config.http_protocol_class is H11Protocol:
            self.config.http_protocol_class = _DrainingH11Protocol
        await super().startup(sockets)


class _Worker(Process):
    """A worker whose health reply also carries how many requests it has served."""

    def __init__(self, config: Config, sockets: list[Any], request_limit: int | None) -> None:
        super().__init__(config, sockets)
        self.request_limit = request_limit
        self.served = 0

    @property
    def server(self) -> Server:
        if self._server is None:
            self._server = _WorkerServer(config=self.config)
        return self._server

    def _healthcheck(self, timeout: float) -> bool | None:
        try:
            self.parent_conn.send(b"ping")
            if self.parent_conn.poll(timeout):
                started, self.served = self.parent_conn.recv()
                return bool(started)
            return None
        except (OSError, EOFError, ValueError, TypeError):
            return None

    def is_ready(self, timeout: float = 0) -> bool:
        # Keep only one outstanding ping while startup is starved of CPU.
        try:
            if not getattr(self, "_ready_ping_pending", False):
                self.parent_conn.send(b"ping")
                self._ready_ping_pending = True
            if not self.parent_conn.poll(timeout):
                return False
            started, self.served = self.parent_conn.recv()
            self._ready_ping_pending = False
            return bool(started)
        except (OSError, EOFError, ValueError, TypeError):
            return False

    def pong(self) -> None:
        self.child_conn.recv()
        self.child_conn.send((self.server.started, self.server.server_state.total_requests))

    def over_limit(self) -> bool:
        return self.request_limit is not None and self.served >= self.request_limit


class RollingMultiprocess(Multiprocess):
    def __init__(self, config: Config, sockets: list[Any]) -> None:
        super().__init__(config, sockets)
        self._limit = config.limit_max_requests
        self._jitter = config.limit_max_requests_jitter
        # The config is pickled into every worker: they must never exit on the limit themselves.
        config.limit_max_requests = None
        self._retiring: list[Process] = []
        self._retirement_started: dict[Process, float] = {}
        self._pending: tuple[Process, _Worker, float] | None = None
        self._restart_queue: list[Process] = []

    def _new_worker(self) -> _Worker:
        limit = None if self._limit is None else self._limit + random.randint(0, self._jitter)
        worker = _Worker(self.config, self.sockets, limit)
        worker.start()
        return worker

    def init_processes(self) -> None:
        self.processes = [self._new_worker() for _ in range(self.processes_num)]

    def restart_all(self) -> None:
        self._restart_queue = list(self.processes)

    def handle_ttin(self) -> None:
        if self.should_exit.is_set():
            return
        self.processes.append(self._new_worker())
        self.processes_num += 1

    def terminate_all(self) -> None:
        super().terminate_all()
        if self._pending is not None:
            self._pending[1].terminate()

    def _drain_timeout(self) -> float:
        timeout = self.config.timeout_graceful_shutdown
        return (30.0 if timeout is None else timeout) + self.config.timeout_worker_healthcheck

    def join_all(self) -> None:
        workers = [*self.processes, *self._retiring]
        if self._pending is not None:
            workers.append(self._pending[1])
        deadline = time.monotonic() + self._drain_timeout()
        for worker in workers:
            worker.process.join(timeout=max(0.0, deadline - time.monotonic()))
            if worker.process.is_alive():
                worker.kill()
            worker.join()

    def keep_subprocess_alive(self) -> None:
        if self.should_exit.is_set():
            return
        for process in self._retiring:
            if (process.process.is_alive() and time.monotonic()
                    - self._retirement_started[process] >= self._drain_timeout()):
                process.kill()
            if not process.process.is_alive():
                process.join()
                self._retirement_started.pop(process, None)
        self._retiring = [p for p in self._retiring if p.process.is_alive()]
        # Dead workers first, without pinging anyone, so one slow reply cannot delay a replacement.
        for idx, process in enumerate(self.processes):
            if not process.process.is_alive():
                self._replace_dead(idx, process)
                if self.should_exit.is_set():
                    return
        for idx, process in enumerate(self.processes):
            if not process.is_alive(timeout=self.config.timeout_worker_healthcheck):
                self._replace_dead(idx, process)
                if self.should_exit.is_set():
                    return
        if self._pending is not None:
            self._advance_recycle()
            return
        while self._restart_queue:
            old = self._restart_queue.pop(0)
            if old in self.processes:
                self._recycle(self.processes.index(old), old)
                return
        for idx, process in enumerate(self.processes):
            if isinstance(process, _Worker) and process.over_limit():
                self._recycle(idx, process)
                return  # one at a time

    def _replace_dead(self, idx: int, process: Process) -> None:
        process.kill()
        process.join()
        if process.exitcode == STARTUP_FAILURE:
            logger.error(f"Child process [{process.pid}] failed to start, stopping the parent process.")
            self.should_exit.set()
            return
        logger.info(f"Child process [{process.pid}] died")
        self.processes[idx] = self._new_worker()

    def _recycle(self, idx: int, old: Process) -> None:
        self._pending = (old, self._new_worker(), time.monotonic())
        self._advance_recycle()

    def _advance_recycle(self) -> None:
        if self._pending is None:
            raise InternalInvariantError("worker recycle requires a pending replacement")
        old, new, started_at = self._pending
        if not new.process.is_alive():
            new.join()
            self._pending = None
            if new.exitcode == STARTUP_FAILURE:
                logger.error(f"Child process [{new.pid}] failed to start, stopping the parent process.")
                self.should_exit.set()
            return
        if old not in self.processes or time.monotonic() - started_at > max(120, self.config.timeout_worker_healthcheck * 10):
            # Startup can already have accepted sockets before reporting ready.
            new.terminate()
            self._retiring.append(new)
            self._retirement_started[new] = time.monotonic()
            self._pending = None
            logger.error(f"Replacement worker [{new.pid}] abandoned; draining gracefully.")
            return
        if not new.is_ready(timeout=0):
            return
        logger.info(f"Worker [{old.pid}] served {getattr(old, 'served', 0)} requests; retiring it behind [{new.pid}].")
        self.processes[self.processes.index(old)] = new
        self._pending = None
        old.terminate()  # graceful drain; reaped on a later tick
        self._retiring.append(old)
        self._retirement_started[old] = time.monotonic()


def main() -> None:
    # The package re-exports the click command as ``uvicorn.main``, hiding the module.
    module = importlib.import_module("uvicorn.main")
    setattr(module, "Multiprocess", RollingMultiprocess)
    module.main()
