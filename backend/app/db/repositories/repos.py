from sqlalchemy import delete, select, text

from backend.app.db.utils import now_iso
from backend.app.models import RepoRecord
from backend.app.services.repo_scanner import RepoDescriptor


class RepoRepositoryMixin:
    def upsert_repo(self, repo: RepoDescriptor) -> RepoDescriptor:
        now = now_iso()
        with self.orm_session() as session:
            record = session.get(RepoRecord, repo.id)
            if record is None:
                session.add(
                    RepoRecord(
                        id=repo.id,
                        name=repo.name,
                        path=repo.path,
                        source_type=repo.source_type,
                        git_url=repo.git_url,
                        commit_hash=repo.commit_hash,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                record.name = repo.name
                record.path = repo.path
                record.source_type = repo.source_type
                record.git_url = repo.git_url
                record.commit_hash = repo.commit_hash
                record.updated_at = now
        return repo

    def get_repo(self, repo_id: str) -> RepoDescriptor | None:
        with self.orm_session() as session:
            record = session.get(RepoRecord, repo_id)
            return _repo_descriptor(record) if record is not None else None

    def list_repos(self) -> list[RepoDescriptor]:
        with self.orm_session() as session:
            records = session.scalars(
                select(RepoRecord).order_by(RepoRecord.updated_at.desc(), RepoRecord.name)
            ).all()
            return [_repo_descriptor(record) for record in records]

    def delete_repo(self, repo_id: str) -> bool:
        with self.orm_session() as session:
            repo = session.get(RepoRecord, repo_id)
            if repo is None:
                return False

            if self.supports_sqlite_vec:
                _delete_vector_rows(session, repo_id)
            if self.supports_fts5:
                session.execute(
                    text("DELETE FROM code_chunk_fts WHERE repo_id = :repo_id"),
                    {"repo_id": repo_id},
                )
            session.execute(delete(RepoRecord).where(RepoRecord.id == repo_id))
            return True


def _repo_descriptor(record: RepoRecord) -> RepoDescriptor:
    return RepoDescriptor(
        id=record.id,
        name=record.name,
        path=record.path,
        source_type=record.source_type,
        git_url=record.git_url,
        commit_hash=record.commit_hash,
    )


def _delete_vector_rows(session, repo_id: str) -> None:
    rows = session.execute(
        text(
            """
        SELECT name
        FROM sqlite_master
        WHERE name LIKE 'code_chunk_embedding_vec_%'
        """
        )
    ).mappings()
    for row in rows:
        table_name = row["name"]
        suffix = table_name.removeprefix("code_chunk_embedding_vec_")
        if suffix.isdigit():
            session.execute(text(f"DELETE FROM {table_name} WHERE repo_id = :repo_id"), {"repo_id": repo_id})
