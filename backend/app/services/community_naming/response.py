import json
import re
from hashlib import sha256
from typing import Any

from backend.app.database import GraphCommunityRecord
from backend.app.services.community_naming.constants import MAX_NAME_LENGTH


def apply_llm_names(
    all_communities: list[GraphCommunityRecord],
    target_communities: list[GraphCommunityRecord],
    content: str,
    *,
    fallback_names: dict[str, str] | None = None,
) -> tuple[list[GraphCommunityRecord], list[str]]:
    errors: list[str] = []
    by_id = {community.id: community for community in all_communities}
    target_ids = {community.id for community in target_communities}
    try:
        payload = json_object(content)
    except ValueError as exc:
        errors.append(str(exc))
        return all_communities, errors

    raw_items = payload.get("communities")
    if not isinstance(raw_items, list):
        errors.append("LLM response must contain a communities array.")
        return all_communities, errors

    updates: dict[str, GraphCommunityRecord] = {}
    seen_names: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            errors.append(f"communities[{index}] must be an object.")
            continue
        community_id = str(raw_item.get("id") or "")
        if community_id not in target_ids:
            errors.append(f"communities[{index}] uses unknown community id.")
            continue
        community = by_id[community_id]
        name = normalize_name(raw_item.get("name"), fallback=community.name)
        if is_generic_name(name):
            fallback_name = (fallback_names or {}).get(community_id) or community.name
            name = non_generic_fallback_name(fallback_name, index=index)
        if is_generic_name(name):
            name = f"Code Area {index + 1}"
        name = dedupe_name(name, seen_names)
        seen_names.add(name.lower())
        summary = normalize_summary(raw_item.get("summary"), fallback=community.summary or "")
        updates[community_id] = GraphCommunityRecord(
            id=community.id,
            repo_id=community.repo_id,
            name=name,
            level=community.level,
            node_ids=community.node_ids,
            summary=summary,
            summary_hash=sha256(summary.encode("utf-8")).hexdigest(),
            created_at=community.created_at,
        )

    return [updates.get(community.id, community) for community in all_communities], errors


def json_object(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError("LLM did not return a JSON object.") from exc
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be a JSON object.")
    return payload


def normalize_name(value: Any, *, fallback: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    name = re.sub(r"^(?:community|cluster)\s+\d+\s*[:\-]\s*", "", name, flags=re.IGNORECASE)
    if not name:
        name = fallback
    name = name[:MAX_NAME_LENGTH].strip(" :-")
    return name or fallback


def normalize_summary(value: Any, *, fallback: str) -> str:
    summary = re.sub(r"\s+", " ", str(value or "").strip())
    if not summary:
        summary = fallback
    return summary[:800].strip()


def is_generic_name(name: str) -> bool:
    normalized = name.lower().strip()
    return normalized in {
        "backend subsystem",
        "frontend subsystem",
        "core subsystem",
        "core",
        "misc",
        "miscellaneous",
        "cluster",
        "community",
    } or re.fullmatch(r"(?:community|cluster)[\s_:#-]*(?:\d+|n)", normalized) is not None


def non_generic_fallback_name(name: str, *, index: int) -> str:
    fallback = f"Code Area {index + 1}"
    candidate = normalize_name(name, fallback=fallback)
    return fallback if is_generic_name(candidate) else candidate


def dedupe_name(name: str, seen_names: set[str]) -> str:
    if name.lower() not in seen_names:
        return name
    suffix = 2
    candidate = f"{name} {suffix}"
    while candidate.lower() in seen_names:
        suffix += 1
        candidate = f"{name} {suffix}"
    return candidate


def renamed_count(
    before: list[GraphCommunityRecord],
    after: list[GraphCommunityRecord],
) -> int:
    before_by_id = {community.id: community for community in before}
    return sum(
        1
        for community in after
        if (previous := before_by_id.get(community.id)) is not None
        and (previous.name != community.name or previous.summary != community.summary)
    )
