from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

JsonObject = dict[str, Any]
ToolHandler = Callable[[JsonObject], Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: JsonObject
    handler: ToolHandler

    def payload(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
