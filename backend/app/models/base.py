from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, ClassVar

from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class JSONText(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, default_factory: Callable[[], Any], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.default_factory = default_factory

    def process_bind_param(self, value: Any, dialect) -> str:
        if value is None:
            value = self.default_factory()
        return json.dumps(value, sort_keys=True)

    def process_result_value(self, value: str | None, dialect) -> Any:
        if value is None or value == "":
            return self.default_factory()
        return json.loads(value)


class RecordMixin:
    __record_fields__: ClassVar[tuple[str, ...]]

    def as_record_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__record_fields__}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.as_record_dict() == other.as_record_dict()

    def __repr__(self) -> str:
        fields = ", ".join(f"{key}={value!r}" for key, value in self.as_record_dict().items())
        return f"{self.__class__.__name__}({fields})"
