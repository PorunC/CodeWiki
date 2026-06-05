from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    for relative_path in [
        ".pytest_cache",
        ".ruff_cache",
        "backend-ts/dist",
        "backend-ts/coverage",
        "backend-ts/static",
        "backend/app/static",
        "frontend/dist",
        "frontend/.vite",
        "frontend/tsconfig.tsbuildinfo",
    ]:
        remove(ROOT / relative_path)
    return 0


def remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
