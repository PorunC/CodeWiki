from __future__ import annotations

import os
import sys


def main() -> int:
    expected = parse_version(os.environ.get("PYTHON_VERSION", "3.12"))
    actual = sys.version_info[:2]
    if actual == expected:
        return 0

    print(
        "Python {}.{} is required for graspologic Leiden community detection; {} is {}.{}. "
        "Recreate .venv with `python{}.{} -m venv .venv` or pass `PYTHON=python{}.{}`.".format(
            *expected,
            sys.executable,
            *actual,
            *expected,
            *expected,
        ),
        file=sys.stderr,
    )
    return 1


def parse_version(value: str) -> tuple[int, int]:
    major, _separator, minor = value.partition(".")
    return int(major), int(minor or "0")


if __name__ == "__main__":
    raise SystemExit(main())
