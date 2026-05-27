import re
from hashlib import sha1, sha256

from backend.app.db.records import GraphCommunityRecord
from backend.app.services.community.detector import DetectedCommunity
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode

MAX_SUMMARY_FILES = 8
MAX_SUMMARY_SYMBOLS = 10
MAX_SUMMARY_EDGES = 8


class CommunityRecordBuilder:
    def build_all(
        self,
        repo_id: str,
        communities: list[DetectedCommunity],
        nodes: list[CodeGraphNode],
        edges: list[CodeGraphEdge],
        algorithm: str,
    ) -> list[GraphCommunityRecord]:
        node_by_id = {node.id: node for node in nodes}
        parent_ids = {
            community.key: self._community_id(repo_id, community)
            for community in communities
        }
        return [
            self.build(repo_id, community, node_by_id, edges, algorithm, parent_ids)
            for community in communities
            if community.node_ids
        ]

    def build(
        self,
        repo_id: str,
        community: DetectedCommunity,
        node_by_id: dict[str, CodeGraphNode],
        edges: list[CodeGraphEdge],
        algorithm: str,
        parent_ids: dict[str, str] | None = None,
    ) -> GraphCommunityRecord:
        node_ids = community.node_ids
        name = self.name(community.rank, node_ids, node_by_id)
        summary = self.summary(
            name,
            node_ids,
            node_by_id,
            edges,
            algorithm,
            level=community.level,
        )
        return GraphCommunityRecord(
            id=self._community_id(repo_id, community),
            repo_id=repo_id,
            name=name,
            level=community.level,
            parent_id=(parent_ids or {}).get(community.parent_key or ""),
            rank=community.rank,
            node_ids=sorted(node_ids),
            summary=summary,
            summary_hash=sha256(summary.encode("utf-8")).hexdigest(),
            created_at=None,
        )

    def name(
        self,
        index: int,
        node_ids: list[str],
        node_by_id: dict[str, CodeGraphNode],
    ) -> str:
        files = self._community_files(node_ids, node_by_id)
        symbols = self._community_symbols(node_ids, node_by_id)
        label = self._name_from_files(files) or self._name_from_symbols(symbols) or "Unclassified Code Area"
        return self._dedupe_words(label)

    def summary(
        self,
        name: str,
        node_ids: list[str],
        node_by_id: dict[str, CodeGraphNode],
        edges: list[CodeGraphEdge],
        algorithm: str,
        *,
        level: int = 0,
    ) -> str:
        node_id_set = set(node_ids)
        files = self._community_files(node_ids, node_by_id)
        symbols = self._community_symbols(node_ids, node_by_id)
        internal_edges = [
            edge
            for edge in edges
            if edge.source_id in node_id_set and edge.target_id in node_id_set
        ]
        boundary_edges = [
            edge
            for edge in edges
            if (edge.source_id in node_id_set) ^ (edge.target_id in node_id_set)
        ]

        if level == 0:
            lines = [
                f"{name} is a parent community detected by {algorithm} and contains {len(node_ids)} graph nodes.",
            ]
        else:
            lines = [
                f"{name} is an implementation community detected by {algorithm} and contains {len(node_ids)} graph nodes.",
            ]
        if files:
            lines.append(f"Key files: {', '.join(files[:MAX_SUMMARY_FILES])}.")
        if symbols:
            lines.append(f"Key symbols: {', '.join(symbols[:MAX_SUMMARY_SYMBOLS])}.")
        if internal_edges:
            lines.append(f"Internal relationships: {self._edge_summary(internal_edges, node_by_id)}.")
        if boundary_edges:
            lines.append(f"Boundary relationships: {self._edge_summary(boundary_edges, node_by_id)}.")
        return " ".join(lines)

    def _community_files(
        self,
        node_ids: list[str],
        node_by_id: dict[str, CodeGraphNode],
    ) -> list[str]:
        return sorted(
            {
                node.file_path
                for node_id in node_ids
                if (node := node_by_id.get(node_id)) is not None and node.file_path
            }
        )

    def _community_symbols(
        self,
        node_ids: list[str],
        node_by_id: dict[str, CodeGraphNode],
    ) -> list[str]:
        symbols = [
            f"{node.name} ({node.type})"
            for node_id in node_ids
            if (node := node_by_id.get(node_id)) is not None and node.type != "file"
        ]
        return sorted(symbols)

    def _name_from_files(self, files: list[str]) -> str:
        labels = [self._file_label(file_path) for file_path in files]
        labels = [label for label in labels if label and label.lower() not in {"index", "main"}]
        if not labels:
            return ""
        unique_labels = self._unique_preserve_order(labels)
        if len(unique_labels) == 1:
            return unique_labels[0]
        if len(unique_labels) == 2:
            return f"{unique_labels[0]} and {unique_labels[1]}"

        directories = self._meaningful_directories(files)
        if directories and len(set(directories)) == 1:
            return f"{self._humanize_stem(directories[0])}: {unique_labels[0]} and {unique_labels[1]}"
        return f"{unique_labels[0]}, {unique_labels[1]}, and {unique_labels[2]}"

    def _file_label(self, file_path: str) -> str:
        file_name = file_path.rsplit("/", 1)[-1]
        if file_name.startswith("__init__."):
            package_name = self._package_name(file_path)
            return f"{self._humanize_stem(package_name)} Package" if package_name else "Python Package"
        return self._humanize_stem(self._file_stem(file_name))

    def _name_from_symbols(self, symbols: list[str]) -> str:
        for symbol in symbols:
            name = symbol.split(" (", 1)[0].strip()
            if name and not name.startswith("_"):
                return self._humanize_stem(name)
        return ""

    def _edge_summary(
        self,
        edges: list[CodeGraphEdge],
        node_by_id: dict[str, CodeGraphNode],
    ) -> str:
        parts = []
        for edge in sorted(edges, key=lambda item: (item.type, item.source_id, item.target_id))[
            :MAX_SUMMARY_EDGES
        ]:
            source = node_by_id.get(edge.source_id)
            target = node_by_id.get(edge.target_id)
            source_label = source.name if source is not None else edge.source_id
            target_label = target.name if target is not None else edge.target_id
            parts.append(f"{source_label} {edge.type} {target_label}")
        return "; ".join(parts)

    @staticmethod
    def _file_stem(file_name: str) -> str:
        if file_name.startswith("."):
            file_name = file_name.lstrip(".")
        return file_name.rsplit(".", 1)[0]

    @staticmethod
    def _package_name(file_path: str) -> str:
        parts = file_path.split("/")[:-1]
        return parts[-1] if parts else ""

    @staticmethod
    def _meaningful_directories(files: list[str]) -> list[str]:
        ignored = {"backend", "frontend", "src", "app", "tests", "test"}
        directories = []
        for file_path in files:
            parts = file_path.split("/")[:-1]
            meaningful = [part for part in parts if part not in ignored]
            if meaningful:
                directories.append(meaningful[-1])
        return directories

    @staticmethod
    def _humanize_stem(value: str) -> str:
        value = re.sub(r"^test_", "", value)
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        value = value.replace("_", " ").replace("-", " ").strip()
        words = [word for word in value.split() if word]
        if not words:
            return ""
        return " ".join(word if word.isupper() else word.capitalize() for word in words)

    @staticmethod
    def _unique_preserve_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for value in values:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(value)
        return unique

    @staticmethod
    def _dedupe_words(value: str) -> str:
        words = value.split()
        deduped: list[str] = []
        for word in words:
            if deduped and deduped[-1].lower().strip(":,") == word.lower().strip(":,"):
                continue
            deduped.append(word)
        return " ".join(deduped)

    @staticmethod
    def _community_id(repo_id: str, community: DetectedCommunity) -> str:
        digest = sha1(
            "|".join(
                [
                    str(community.level),
                    community.parent_key or "",
                    *sorted(community.node_ids),
                ]
            ).encode("utf-8")
        ).hexdigest()[:16]
        return f"{repo_id}:community:{community.level}:{digest}"
