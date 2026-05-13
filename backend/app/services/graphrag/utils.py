import hashlib
import re
from typing import Any

from backend.app.database import CodeChunkRecord
from backend.app.services.graph import CodeGraphNode

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")


def node_haystack(node: CodeGraphNode) -> str:
    values: list[str] = [
        node.name,
        node.type,
        node.file_path,
        node.symbol_id or "",
        node.language or "",
    ]
    for key in ("signature", "docstring", "route_method", "route_path", "handler"):
        value = node.metadata.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("fields", "bases", "decorators", "exports", "calls"):
        value = node.metadata.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item is not None)
    return " ".join(values).lower()


def node_type_boost(node_type: str) -> float:
    return {
        "endpoint": 0.12,
        "function": 0.1,
        "method": 0.1,
        "class": 0.08,
        "schema": 0.08,
        "file": 0.04,
        "module": -0.1,
    }.get(node_type, 0.0)


def terms(value: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(value)]


def fts_query(query: str) -> str:
    query_terms = []
    seen = set()
    for term in terms(query):
        if term in seen:
            continue
        seen.add(term)
        query_terms.append(term)
    return " OR ".join(f'"{term}"' for term in query_terms[:16])


def estimate_tokens(content: str) -> int:
    return max(1, len(re.findall(r"\S+", content)))


def embedding_text(chunk: CodeChunkRecord) -> str:
    return f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}\n{chunk.content}"


def stable_id(repo_id: str, kind: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{repo_id}:{kind}:{digest}"


def batched(items: list[Any], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]
