from dataclasses import dataclass
from typing import Any

from sqlalchemy import Table
from sqlalchemy.dialects import postgresql, sqlite


@dataclass(frozen=True)
class DatabaseDialect:
    name: str

    @property
    def supports_fts5(self) -> bool:
        return self.name == "sqlite"

    @property
    def supports_sqlite_vec(self) -> bool:
        return self.name == "sqlite"

    def insert_ignore(self, table: Table, conflict_columns: list[str]):
        if self.name == "postgresql":
            return postgresql.insert(table).on_conflict_do_nothing(
                index_elements=conflict_columns
            )
        if self.name == "sqlite":
            return sqlite.insert(table).on_conflict_do_nothing(index_elements=conflict_columns)
        raise ValueError(f"Unsupported database dialect: {self.name}")

    def upsert(self, table: Table, conflict_columns: list[str], update_columns: list[str]):
        if self.name == "postgresql":
            statement = postgresql.insert(table)
        elif self.name == "sqlite":
            statement = sqlite.insert(table)
        else:
            raise ValueError(f"Unsupported database dialect: {self.name}")
        return statement.on_conflict_do_update(
            index_elements=conflict_columns,
            set_={column: getattr(statement.excluded, column) for column in update_columns},
        )

    def ilike(self, column: str, parameter: str) -> str:
        if self.name == "postgresql":
            return f"{column} ILIKE {parameter}"
        return f"lower({column}) LIKE lower({parameter})"

    def ignore_values(self, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return values
