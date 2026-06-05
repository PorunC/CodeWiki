from __future__ import annotations

import importlib.util
import signal
import sys
from pathlib import Path


def _load_dev_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "dev.py"
    spec = importlib.util.spec_from_file_location("dev_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dev_script = _load_dev_module()


def test_main_refuses_to_start_when_dev_ports_are_occupied(monkeypatch, capsys) -> None:
    monkeypatch.setattr(dev_script, "listener_pids_by_port", lambda _ports: {8000: {1234}})

    def fail_if_started(*_args, **_kwargs) -> None:
        raise AssertionError("dev servers should not start when a port is occupied")

    monkeypatch.setattr(dev_script.subprocess, "Popen", fail_if_started)

    assert dev_script.main() == 1

    output = capsys.readouterr().out
    assert "Cannot start dev servers" in output
    assert "port 8000: PID(s) 1234" in output
    assert "make kill" in output


def test_main_starts_typescript_backend(monkeypatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(dev_script, "listener_pids_by_port", lambda _ports: {})
    monkeypatch.setattr(dev_script, "wait_for_processes", lambda _processes: 0)

    def fake_popen(args, *_positional, **_kwargs):
        commands.append(args)
        return object()

    monkeypatch.setattr(dev_script.subprocess, "Popen", fake_popen)

    assert dev_script.main() == 0

    backend_command = commands[0]
    assert backend_command[:5] == [
        "npm",
        "--prefix",
        str(dev_script.ROOT / "backend"),
        "run",
        "dev",
    ]
    assert "serve" in backend_command
    assert "--static-dir" in backend_command
    assert str(dev_script.ROOT / "backend" / "static") in backend_command


def test_normalize_return_code_treats_sigterm_as_graceful_shutdown() -> None:
    assert dev_script.normalize_return_code(-int(signal.SIGTERM)) == 0
    assert dev_script.normalize_return_code(1) == 1
