import type { SourceRef } from "../api/types";
import { dispatchOpenSourceRef } from "../graph/navigationEvents";

export function openSourceInGraph(repoId: string, source: SourceRef) {
  dispatchOpenSourceRef(
    {
      repoId,
      filePath: source.file_path,
      startLine: source.start_line,
      endLine: source.end_line
    },
    { navigateToGraph: true }
  );
}
