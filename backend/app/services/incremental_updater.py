class IncrementalUpdater:
    def plan(self, repo_id: str) -> dict[str, list[str]]:
        return {"repo_id": [repo_id], "changed_files": [], "deleted_files": [], "unchanged_files": []}

