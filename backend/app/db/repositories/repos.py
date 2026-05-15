from backend.app.db.utils import now_iso
from backend.app.services.repo_scanner import RepoDescriptor


class RepoRepositoryMixin:
    def upsert_repo(self, repo: RepoDescriptor) -> RepoDescriptor:
        now = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO repo (id, name, path, source_type, git_url, commit_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  path = excluded.path,
                  source_type = excluded.source_type,
                  git_url = excluded.git_url,
                  commit_hash = excluded.commit_hash,
                  updated_at = excluded.updated_at
                """,
                (repo.id, repo.name, repo.path, repo.source_type, repo.git_url, repo.commit_hash, now),
            )
        return repo

    def get_repo(self, repo_id: str) -> RepoDescriptor | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, name, path, source_type, git_url, commit_hash FROM repo WHERE id = ?",
                (repo_id,),
            ).fetchone()
        if row is None:
            return None
        return RepoDescriptor(
            id=row["id"],
            name=row["name"],
            path=row["path"],
            source_type=row["source_type"],
            git_url=row["git_url"],
            commit_hash=row["commit_hash"],
        )

    def list_repos(self) -> list[RepoDescriptor]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, path, source_type, git_url, commit_hash
                FROM repo
                ORDER BY updated_at DESC, name
                """
            ).fetchall()
        return [
            RepoDescriptor(
                id=row["id"],
                name=row["name"],
                path=row["path"],
                source_type=row["source_type"],
                git_url=row["git_url"],
                commit_hash=row["commit_hash"],
            )
            for row in rows
        ]

    def delete_repo(self, repo_id: str) -> bool:
        with self.connect() as connection:
            repo_exists = connection.execute(
                "SELECT 1 FROM repo WHERE id = ?",
                (repo_id,),
            ).fetchone()
            if repo_exists is None:
                return False

            _delete_vector_rows(connection, repo_id)
            connection.execute("DELETE FROM code_chunk_fts WHERE repo_id = ?", (repo_id,))
            connection.execute("DELETE FROM repo WHERE id = ?", (repo_id,))
            return True


def _delete_vector_rows(connection, repo_id: str) -> None:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE name LIKE 'code_chunk_embedding_vec_%'
        """
    ).fetchall()
    for row in rows:
        table_name = row["name"]
        suffix = table_name.removeprefix("code_chunk_embedding_vec_")
        if suffix.isdigit():
            connection.execute(f"DELETE FROM {table_name} WHERE repo_id = ?", (repo_id,))
