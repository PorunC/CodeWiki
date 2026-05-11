from backend.app.services.ast_parser import AstSymbol


class GraphBuilder:
    def build_from_symbols(self, repo_id: str, symbols: list[AstSymbol]) -> dict[str, object]:
        nodes = [
            {
                "id": symbol.id,
                "type": symbol.type,
                "name": symbol.name,
                "file_path": symbol.file_path,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
            }
            for symbol in symbols
        ]
        return {"repo_id": repo_id, "nodes": nodes, "edges": []}

