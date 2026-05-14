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


def test_kill_process_ignores_already_exited_process(monkeypatch) -> None:
    if os.name == "nt":
        return

    def raise_process_lookup_error(_pid: int, _signal: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(kill_ports.os, "kill", raise_process_lookup_error)

    kill_ports.kill_process(1234)
