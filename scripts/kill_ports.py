from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time


DEFAULT_PORTS = [8000, 5173]
DEFAULT_TIMEOUT_SECONDS = 5.0


def main(argv: list[str]) -> int:
    check_only, ports = parse_args(argv)
    occupied = listener_pids_by_port(ports)
    if not occupied:
        print(f"No matching listeners on ports {', '.join(str(port) for port in ports)}")
        return 0

    if check_only:
        print("Ports are already in use.")
        print(format_listener_summary(occupied))
        return 1

    pids = {pid for port_pids in occupied.values() for pid in port_pids}
    current_pid = os.getpid()
    signaled_targets: set[tuple[str, int]] = set()
    for pid in sorted(pid for pid in pids if pid != current_pid):
        target = signal_target(pid)
        if target in signaled_targets:
            continue
        signaled_targets.add(target)
        print(f"Stopping {describe_signal_target(target)} for PID {pid}")
        kill_process(pid)
    remaining = wait_for_ports_to_clear(ports, DEFAULT_TIMEOUT_SECONDS)
    if not remaining:
        return 0

    print("Ports are still in use after graceful shutdown; forcing remaining listeners to stop.")
    signaled_targets.clear()
    remaining_pids = {pid for port_pids in remaining.values() for pid in port_pids}
    force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    for pid in sorted(pid for pid in remaining_pids if pid != current_pid):
        target = signal_target(pid)
        if target in signaled_targets:
            continue
        signaled_targets.add(target)
        print(f"Force killing {describe_signal_target(target)} for PID {pid}")
        kill_process(pid, force_signal)

    final_remaining = wait_for_ports_to_clear(ports, 2.0)
    if final_remaining:
        print("Some ports are still in use.")
        print(format_listener_summary(final_remaining))
        return 1
    return 0


def parse_args(argv: list[str]) -> tuple[bool, list[int]]:
    check_only = False
    port_args: list[str] = []
    for arg in argv:
        if arg == "--check":
            check_only = True
        else:
            port_args.append(arg)
    ports = [parse_port(arg) for arg in port_args] if port_args else DEFAULT_PORTS
    return check_only, ports


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise SystemExit(f"Port must be an integer, got {value!r}") from None
    if not 1 <= port <= 65535:
        raise SystemExit(f"Port must be between 1 and 65535, got {port}")
    return port


def listener_pids_by_port(ports: list[int]) -> dict[int, set[int]]:
    occupied: dict[int, set[int]] = {}
    for port in ports:
        pids = listener_pids([port])
        if pids:
            occupied[port] = pids
    return occupied


def format_listener_summary(occupied: dict[int, set[int]]) -> str:
    return "\n".join(
        f"  port {port}: PID(s) {', '.join(str(pid) for pid in sorted(pids))}"
        for port, pids in sorted(occupied.items())
    )


def wait_for_ports_to_clear(ports: list[int], timeout_seconds: float) -> dict[int, set[int]]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = listener_pids_by_port(ports)
        if not remaining or time.monotonic() >= deadline:
            return remaining
        time.sleep(0.2)


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


def signal_target(pid: int) -> tuple[str, int]:
    if os.name == "nt":
        return ("pid", pid)
    try:
        process_group_id = os.getpgid(pid)
    except ProcessLookupError:
        return ("pid", pid)
    if process_group_id != os.getpgrp():
        return ("pgid", process_group_id)
    return ("pid", pid)


def describe_signal_target(target: tuple[str, int]) -> str:
    kind, value = target
    if kind == "pgid":
        return f"process group {value}"
    return f"PID {value}"


def kill_process(pid: int, sig: signal.Signals = signal.SIGTERM) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        target = signal_target(pid)
        if target[0] == "pgid":
            try:
                os.killpg(target[1], sig)
            except PermissionError:
                os.kill(pid, sig)
        else:
            os.kill(target[1], sig)
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
