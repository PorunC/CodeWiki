from backend.app.db.utils import now_iso
from backend.app.services.repo_scanner import RepoDescriptor


class RepoRepositoryMixin:
    def upsert_repo(self, repo: RepoDescriptor) -> RepoDescriptor:
        now = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO repo (id, name, path, source_type, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  path = excluded.path,
                  source_type = excluded.source_type,
                  updated_at = excluded.updated_at
                """,
                (repo.id, repo.name, repo.path, repo.source_type, now),
            )
        return repo

    def get_repo(self, repo_id: str) -> RepoDescriptor | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, name, path, source_type FROM repo WHERE id = ?",
                (repo_id,),
            ).fetchone()
        if row is None:
            return None
        return RepoDescriptor(
            id=row["id"],
            name=row["name"],
            path=row["path"],
            source_type=row["source_type"],
        )

    def list_repos(self) -> list[RepoDescriptor]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, path, source_type FROM repo ORDER BY updated_at DESC, name"
            ).fetchall()
        return [
            RepoDescriptor(
                id=row["id"],
                name=row["name"],
                path=row["path"],
                source_type=row["source_type"],
            )
            for row in rows
        ]

