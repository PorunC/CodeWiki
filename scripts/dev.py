from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.kill_ports import format_listener_summary, listener_pids_by_port
except ModuleNotFoundError:
    from kill_ports import format_listener_summary, listener_pids_by_port


@dataclass(frozen=True)
class DevConfig:
    backend_app: str
    backend_host: str
    backend_port: int
    frontend_port: int

    @classmethod
    def from_env(cls) -> "DevConfig":
        return cls(
            backend_app=os.environ.get("BACKEND_APP", "backend.app.main:app"),
            backend_host=os.environ.get("BACKEND_HOST", "127.0.0.1"),
            backend_port=port_from_env("BACKEND_PORT", 8000),
            frontend_port=port_from_env("FRONTEND_PORT", 5173),
        )


def main() -> int:
    config = DevConfig.from_env()
    occupied = listener_pids_by_port([config.backend_port, config.frontend_port])
    if occupied:
        print("Cannot start dev servers because one or more ports are already in use.")
        print(format_listener_summary(occupied))
        print("Run `make kill` to stop existing listeners, or `make restart` to kill and start.")
        print("You can also override BACKEND_PORT or FRONTEND_PORT.")
        return 1

    backend = [
        sys.executable,
        "-m",
        "uvicorn",
        config.backend_app,
        "--reload",
        "--host",
        config.backend_host,
        "--port",
        str(config.backend_port),
    ]
    frontend = [
        sys.executable,
        str(ROOT / "scripts" / "frontend_npm.py"),
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(config.frontend_port),
    ]

    print(f"Starting backend on http://{config.backend_host}:{config.backend_port}", flush=True)
    backend_process = subprocess.Popen(backend, cwd=ROOT, **process_group_kwargs())
    print(f"Starting frontend on http://127.0.0.1:{config.frontend_port}", flush=True)
    frontend_process = subprocess.Popen(frontend, cwd=ROOT, **process_group_kwargs())
    return wait_for_processes([backend_process, frontend_process])


def port_from_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        port = int(value)
    except ValueError:
        raise SystemExit(f"{name} must be an integer, got {value!r}") from None
    if not 1 <= port <= 65535:
        raise SystemExit(f"{name} must be between 1 and 65535, got {port}")
    return port


def process_group_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def wait_for_processes(processes: list[subprocess.Popen[object]]) -> int:
    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    terminate_all(processes, skip=process)
                    return normalize_return_code(return_code)
            time.sleep(0.25)
    except KeyboardInterrupt:
        terminate_all(processes)
        return 130


def normalize_return_code(return_code: int) -> int:
    if return_code < 0 and -return_code in graceful_exit_signals():
        return 0
    return return_code


def graceful_exit_signals() -> set[int]:
    signals = {signal.SIGTERM, signal.SIGINT}
    if hasattr(signal, "SIGHUP"):
        signals.add(signal.SIGHUP)
    return {int(item) for item in signals}


def terminate_all(
    processes: list[subprocess.Popen[object]],
    *,
    skip: subprocess.Popen[object] | None = None,
) -> None:
    for process in processes:
        if process is skip or process.poll() is not None:
            continue
        terminate_process(process)
    for process in processes:
        if process is skip or process.poll() is not None:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def terminate_process(process: subprocess.Popen[object]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        try:
            process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return


if __name__ == "__main__":
    raise SystemExit(main())
