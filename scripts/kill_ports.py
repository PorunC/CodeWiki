from __future__ import annotations

import os
import re
import signal
import subprocess
import sys


def main(argv: list[str]) -> int:
    ports = [int(arg) for arg in argv] if argv else [8000, 5173]
    pids = listener_pids(ports)
    if not pids:
        print(f"No matching listeners on ports {', '.join(str(port) for port in ports)}")
        return 0

    current_pid = os.getpid()
    for pid in sorted(pid for pid in pids if pid != current_pid):
        print(f"Killing PID {pid}")
        kill_process(pid)
    return 0


def listener_pids(ports: list[int]) -> set[int]:
    if os.name == "nt":
        return windows_listener_pids(ports)
    return posix_listener_pids(ports)


def windows_listener_pids(ports: list[int]) -> set[int]:
    output = run(["netstat", "-ano", "-p", "tcp"])
    pids: set[int] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[-2].upper() != "LISTENING" or not parts[-1].isdigit():
            continue
        if port_from_address(parts[1]) in ports:
            pids.add(int(parts[-1]))
    return pids


def posix_listener_pids(ports: list[int]) -> set[int]:
    pids: set[int] = set()
    for port in ports:
        pids.update(pids_from_lsof(port))
        pids.update(pids_from_fuser(port))
    if not pids:
        pids.update(pids_from_ss_or_netstat(ports))
    return pids


def pids_from_lsof(port: int) -> set[int]:
    output = run(["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"])
    return {int(line) for line in output.splitlines() if line.strip().isdigit()}


def pids_from_fuser(port: int) -> set[int]:
    try:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return set()
    return parse_fuser_pids(port, result.stdout, result.stderr)


def parse_fuser_pids(port: int, stdout: str, stderr: str = "") -> set[int]:
    pids: set[int] = set()
    port_label = f"{port}/tcp"
    for line in f"{stdout}\n{stderr}".splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if port_label in stripped:
            _prefix, _separator, tail = stripped.partition(port_label)
            tail = tail.split(":", 1)[1] if ":" in tail else ""
        else:
            tail = stripped
        tokens = tail.split()
        if tokens and all(token.isdigit() for token in tokens):
            pids.update(int(token) for token in tokens)
    return pids


def pids_from_ss_or_netstat(ports: list[int]) -> set[int]:
    output = run(["ss", "-ltnp"]) or run(["netstat", "-ltnp"])
    pids: set[int] = set()
    for line in output.splitlines():
        if not any(port_from_line(line) == port for port in ports):
            continue
        pids.update(int(match) for match in re.findall(r"pid=(\d+)", line))
        pids.update(int(match) for match in re.findall(r"\b(\d+)/", line))
    return pids


def port_from_address(value: str) -> int | None:
    match = re.search(r"[:.](\d+)$", value)
    return int(match.group(1)) if match else None


def port_from_line(line: str) -> int | None:
    match = re.search(r"[:.](\d+)\s", f"{line} ")
    return int(match.group(1)) if match else None


def kill_process(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"PID {pid} already exited")


def run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return ""
    return f"{result.stdout}\n{result.stderr}"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
