from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    frontend_dir = resolve_from_root(os.environ.get("FRONTEND_DIR", "frontend"))
    npm = os.environ.get("NPM", "npm")
    npm_path = shutil.which(npm) or npm

    if is_wsl() and is_windows_tool_on_wsl(npm_path):
        print(
            "\n".join(
                [
                    f"Windows npm was found first on PATH: {npm_path}",
                    "This repository is inside the WSL filesystem, so frontend dependencies must be managed with Linux npm.",
                    "Install Node.js/npm inside WSL, remove Windows Node from the WSL PATH, or pass NPM=/path/to/linux/npm.",
                    "",
                    "Examples:",
                    "  sudo apt install nodejs npm",
                    "  make install-frontend",
                    "  make start",
                ]
            ),
            file=sys.stderr,
        )
        return 127

    return subprocess.run(npm_command(npm_path, argv), cwd=frontend_dir, check=False).returncode


def resolve_from_root(path_value: str) -> Path:
    path = Path(path_value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def npm_command(npm_path: str, argv: list[str]) -> list[str]:
    if os.name == "nt" and npm_path.lower().endswith(".ps1"):
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            npm_path,
            *argv,
        ]
    return [npm_path, *argv]


def is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def is_windows_tool_on_wsl(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.startswith("/mnt/") or normalized.endswith((".exe", ".cmd", ".bat", ".ps1"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
