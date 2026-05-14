from __future__ import annotations

import subprocess
import sys


def main() -> int:
    if subprocess.run([sys.executable, "-m", "pip", "--version"], check=False).returncode == 0:
        return 0
    print(f"pip is missing for {sys.executable}; bootstrapping it with ensurepip")
    return subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
