import re
import asyncio
import subprocess
import sys

MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(?P<body>.*?)```", re.DOTALL | re.IGNORECASE)


def validate_mermaid_blocks(markdown: str) -> list[str]:
    errors: list[str] = []
    for index, block in enumerate(_mermaid_blocks(markdown), start=1):
        error = validate_mermaid(block)
        if error:
            errors.append(f"Mermaid block {index}: {error}")
    return errors


async def validate_mermaid_blocks_async(markdown: str) -> list[str]:
    return await asyncio.to_thread(validate_mermaid_blocks, markdown)


def validate_mermaid(mermaid: str) -> str | None:
    stripped = mermaid.strip()
    if not stripped:
        return "diagram is empty."
    result = subprocess.run(
        [sys.executable, "-c", _MERMAID_VALIDATE_SCRIPT],
        input=stripped,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        return _compact_error(result.stderr or result.stdout)
    return None


def _mermaid_blocks(markdown: str) -> list[str]:
    return [match.group("body") for match in MERMAID_BLOCK_RE.finditer(markdown)]


def _compact_error(message: str) -> str:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return "parser rejected the diagram."
    for index, line in enumerate(lines):
        if "Parse error" not in line:
            continue
        details = [line]
        details.extend(next_line for next_line in lines[index + 1 : index + 5] if "Expecting" in next_line)
        return " ".join(details)[:240]
    return lines[0][:240]


_MERMAID_VALIDATE_SCRIPT = """
import contextlib
import io
import sys

try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from mermaid_parser import MermaidParser
        MermaidParser().parse(sys.stdin.read())
except Exception as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
"""
