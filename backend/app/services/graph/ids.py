import hashlib


def file_node_id(repo_id: str, file_path: str) -> str:
    return f"{repo_id}:file:{file_path}"


def directory_node_id(repo_id: str, directory_path: str) -> str:
    return f"{repo_id}:dir:{directory_path}"


def symbol_node_id(repo_id: str, symbol_id: str) -> str:
    return f"{repo_id}:symbol:{symbol_id}"


def module_node_id(repo_id: str, import_name: str) -> str:
    return f"{repo_id}:module:{import_name}"


def edge_id(repo_id: str, source_id: str, target_id: str, edge_type: str) -> str:
    digest = hashlib.sha1(f"{source_id}|{edge_type}|{target_id}".encode("utf-8")).hexdigest()[:20]
    return f"{repo_id}:edge:{digest}"
