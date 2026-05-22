from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def write_batch_size(dialect_name: str) -> int:
    if dialect_name == "postgresql":
        return 2000
    return 500


def chunks(items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[index:index + size] for index in range(0, len(items), size)]
