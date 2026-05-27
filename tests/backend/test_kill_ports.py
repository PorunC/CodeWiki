from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _load_kill_ports_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "kill_ports.py"
    spec = importlib.util.spec_from_file_location("kill_ports", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kill_ports = _load_kill_ports_module()


def test_parse_fuser_pids_ignores_macos_missing_port_error() -> None:
    stderr = """
perl: warning: Setting locale failed.
/usr/bin/fuser: '8000/tcp' does not exist
"""

    assert kill_ports.parse_fuser_pids(8000, "", stderr) == set()


def test_parse_fuser_pids_accepts_labeled_and_stdout_only_pid_formats() -> None:
    assert kill_ports.parse_fuser_pids(8000, "8000/tcp: 1234 5678") == {1234, 5678}
    assert kill_ports.parse_fuser_pids(8000, "1234 5678", "8000/tcp:") == {1234, 5678}


def test_parse_args_supports_check_mode_and_default_ports() -> None:
    assert kill_ports.parse_args(["--check", "9000"]) == (True, [9000])
    assert kill_ports.parse_args([]) == (False, [8000, 5173])


def test_format_listener_summary_orders_ports_and_pids() -> None:
    summary = kill_ports.format_listener_summary({5173: {22, 11}, 8000: {33}})

    assert summary == "  port 5173: PID(s) 11, 22\n  port 8000: PID(s) 33"


def test_kill_process_ignores_already_exited_process(monkeypatch) -> None:
    if os.name == "nt":
        return

    def raise_process_lookup_error(_pid: int, _signal: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(kill_ports.os, "kill", raise_process_lookup_error)

    kill_ports.kill_process(1234)


def test_kill_process_falls_back_to_pid_when_process_group_is_denied(monkeypatch) -> None:
    if os.name == "nt":
        return

    def raise_permission_error(_pgid: int, _signal: int) -> None:
        raise PermissionError

    def raise_process_lookup_error(_pid: int, _signal: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(kill_ports, "signal_target", lambda _pid: ("pgid", 4321))
    monkeypatch.setattr(kill_ports.os, "killpg", raise_permission_error)
    monkeypatch.setattr(kill_ports.os, "kill", raise_process_lookup_error)

    kill_ports.kill_process(1234)
