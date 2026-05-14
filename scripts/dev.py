from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    backend_app = os.environ.get("BACKEND_APP", "backend.app.main:app")
    backend_host = os.environ.get("BACKEND_HOST", "127.0.0.1")
    backend_port = os.environ.get("BACKEND_PORT", "8000")
    frontend_port = os.environ.get("FRONTEND_PORT", "5173")

    backend = [
        sys.executable,
        "-m",
        "uvicorn",
        backend_app,
        "--reload",
        "--host",
        backend_host,
        "--port",
        backend_port,
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
        frontend_port,
    ]

    print(f"Starting backend on http://{backend_host}:{backend_port}", flush=True)
    backend_process = subprocess.Popen(backend, cwd=ROOT)
    print(f"Starting frontend on http://127.0.0.1:{frontend_port}", flush=True)
    frontend_process = subprocess.Popen(frontend, cwd=ROOT)
    return wait_for_processes([backend_process, frontend_process])


def wait_for_processes(processes: list[subprocess.Popen[object]]) -> int:
    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    terminate_all(processes, skip=process)
                    return return_code
            time.sleep(0.25)
    except KeyboardInterrupt:
        terminate_all(processes)
        return 130


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
        process.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        return


if __name__ == "__main__":
    raise SystemExit(main())
