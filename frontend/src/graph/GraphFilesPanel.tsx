import { ChevronDown, ChevronRight, FileCode2, Folder, FolderOpen, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getRepoFiles } from "../api/files";
import type { GraphResponse, RepoFileRecord, RepoFilesResponse, RepoFileTreeNode } from "../api/types";
import { isFileLikeNode } from "./formatters";

type TreeRow = {
  node: RepoFileTreeNode;
  depth: number;
};

export function GraphFilesPanel({
  selectedRepoId,
  graph,
  selectedFileId,
  onOpenFile
}: {
  selectedRepoId: string;
  graph: GraphResponse | null;
  selectedFileId: string | null;
  onOpenFile: (fileId: string) => void;
}) {
  const [fileData, setFileData] = useState<RepoFilesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!selectedRepoId) {
      setFileData(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    getRepoFiles(selectedRepoId)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setFileData(data);
        setExpandedPaths(new Set(collectDirectoryPaths(data.root)));
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setError(apiError instanceof Error ? apiError.message : "Failed to load files");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [reloadToken, selectedRepoId]);

  const fileNodeIdByPath = useMemo(() => {
    const byPath = new Map<string, string>();
    for (const node of graph?.nodes ?? []) {
      if (isFileLikeNode(node) && node.file_path) {
        byPath.set(node.file_path, node.id);
      }
    }
    return byPath;
  }, [graph?.nodes]);

  const selectedFilePath = useMemo(() => {
    for (const [path, nodeId] of fileNodeIdByPath) {
      if (nodeId === selectedFileId) {
        return path;
      }
    }
    return "";
  }, [fileNodeIdByPath, selectedFileId]);

  const filteredFiles = useMemo(
    () => filterFiles(fileData?.files ?? [], query),
    [fileData, query]
  );
  const treeRows = useMemo(
    () => (fileData && !query.trim() ? flattenTree(fileData.root, expandedPaths) : []),
    [expandedPaths, fileData, query]
  );
  const sourceCount = fileData?.files.filter((file) => file.is_source).length ?? 0;

  return (
    <section className="graph-file-panel" aria-label="Repository files">
      <header className="graph-sidebar-header">
        <div>
          <span className="filter-title">Files</span>
          <strong>{fileData?.files.length ?? 0} total</strong>
        </div>
        <button
          className="icon-button"
          type="button"
          title="Refresh files"
          aria-label="Refresh files"
          disabled={!selectedRepoId || loading}
          onClick={() => setReloadToken((value) => value + 1)}
        >
          <RefreshCw size={14} />
        </button>
      </header>

      <label className="graph-file-search">
        <Search size={14} />
        <input
          value={query}
          placeholder="Filter files"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>

      <div className="graph-file-stats">
        <span>{sourceCount} source</span>
        <span>{fileData?.skipped_count ?? 0} skipped</span>
      </div>

      {loading ? <div className="graph-sidebar-state">Loading files...</div> : null}
      {!loading && error ? <div className="graph-sidebar-state is-error">{error}</div> : null}
      {!loading && !selectedRepoId ? <div className="graph-sidebar-state">Select a repository.</div> : null}

      {fileData && query.trim() ? (
        <GraphFileList
          files={filteredFiles}
          fileNodeIdByPath={fileNodeIdByPath}
          selectedFilePath={selectedFilePath}
          onOpenFile={onOpenFile}
        />
      ) : fileData ? (
        <div className="file-tree graph-file-tree" role="tree" aria-label="Repository file tree">
          {treeRows.map(({ node, depth }) => (
            <GraphFileTreeRow
              key={`${node.type}:${node.path || "__root"}`}
              node={node}
              depth={depth}
              expanded={expandedPaths.has(node.path)}
              fileNodeId={node.path ? fileNodeIdByPath.get(node.path) : undefined}
              selected={node.path === selectedFilePath}
              onToggle={() => toggleExpandedPath(node.path, setExpandedPaths)}
              onOpenFile={onOpenFile}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function GraphFileTreeRow({
  node,
  depth,
  expanded,
  fileNodeId,
  selected,
  onToggle,
  onOpenFile
}: {
  node: RepoFileTreeNode;
  depth: number;
  expanded: boolean;
  fileNodeId?: string;
  selected: boolean;
  onToggle: () => void;
  onOpenFile: (fileId: string) => void;
}) {
  if (node.type === "directory") {
    const Icon = expanded ? FolderOpen : Folder;
    return (
      <div className="file-tree-row is-directory" role="treeitem">
        <button type="button" style={{ paddingLeft: depth * 14 + 8 }} onClick={onToggle}>
          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          <Icon size={14} />
          <span>{node.name}</span>
        </button>
      </div>
    );
  }

  return (
    <div className={`file-tree-row is-file${selected ? " is-selected" : ""}`} role="treeitem">
      <button
        type="button"
        className="graph-file-row"
        style={{ paddingLeft: depth * 14 + 28 }}
        disabled={!fileNodeId}
        title={fileNodeId ? node.path : "File is not present in the current graph"}
        onClick={() => {
          if (fileNodeId) {
            onOpenFile(fileNodeId);
          }
        }}
      >
        <FileCode2 size={14} />
        <span>{node.name}</span>
        <strong>{node.language}</strong>
      </button>
    </div>
  );
}

function GraphFileList({
  files,
  fileNodeIdByPath,
  selectedFilePath,
  onOpenFile
}: {
  files: RepoFileRecord[];
  fileNodeIdByPath: Map<string, string>;
  selectedFilePath: string;
  onOpenFile: (fileId: string) => void;
}) {
  if (files.length === 0) {
    return <div className="graph-sidebar-state">No matching files.</div>;
  }

  return (
    <div className="graph-file-list">
      {files.map((file) => {
        const fileNodeId = fileNodeIdByPath.get(file.path);
        return (
          <button
            key={file.path}
            type="button"
            className={`graph-file-list-row${file.path === selectedFilePath ? " is-selected" : ""}`}
            disabled={!fileNodeId}
            title={file.path}
            onClick={() => {
              if (fileNodeId) {
                onOpenFile(fileNodeId);
              }
            }}
          >
            <FileCode2 size={14} />
            <span>{file.path}</span>
            <strong>{file.language}</strong>
          </button>
        );
      })}
    </div>
  );
}

function flattenTree(
  node: RepoFileTreeNode,
  expandedPaths: Set<string>,
  depth = 0,
  rows: TreeRow[] = []
): TreeRow[] {
  rows.push({ node, depth });
  if (node.type !== "directory" || !expandedPaths.has(node.path)) {
    return rows;
  }
  for (const child of node.children ?? []) {
    flattenTree(child, expandedPaths, depth + 1, rows);
  }
  return rows;
}

function collectDirectoryPaths(node: RepoFileTreeNode, paths: string[] = []): string[] {
  if (node.type === "directory") {
    paths.push(node.path);
    for (const child of node.children ?? []) {
      collectDirectoryPaths(child, paths);
    }
  }
  return paths;
}

function toggleExpandedPath(path: string, setExpandedPaths: (value: (current: Set<string>) => Set<string>) => void) {
  setExpandedPaths((current) => {
    const next = new Set(current);
    if (next.has(path)) {
      next.delete(path);
    } else {
      next.add(path);
    }
    return next;
  });
}

function filterFiles(files: RepoFileRecord[], query: string): RepoFileRecord[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return files;
  }
  return files.filter(
    (file) =>
      file.path.toLowerCase().includes(normalized) ||
      file.language.toLowerCase().includes(normalized)
  );
}
