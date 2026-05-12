from pathlib import Path

from backend.app.services.ast_parser import AstParser


def test_python_parser_extracts_symbols_imports_and_calls(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        "\n".join(
            [
                "import os",
                "from pathlib import Path",
                "",
                "class Service:",
                "    def run(self):",
                "        return Path(os.getcwd())",
                "",
                "def build():",
                "    service = Service()",
                "    return service.run()",
            ]
        )
        + "\n"
    )

    symbols = AstParser().parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert "file:app.py" in by_id
    assert by_id["file:app.py"].imports == ["os", "pathlib.Path"]
    assert by_id["app.py::Service"].type == "class"
    assert by_id["app.py::Service.run"].type == "method"
    assert "Path" in by_id["app.py::Service.run"].calls
    assert by_id["app.py::build"].type == "function"
    assert "Service" in by_id["app.py::build"].calls


def test_tree_sitter_typescript_parser_extracts_basic_symbols(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text(
        "\n".join(
            [
                "import { readFile } from 'node:fs/promises';",
                "export interface UserDto { id: string; name?: string }",
                "export type Status = 'ok' | 'bad';",
                "export class Loader extends BaseLoader {}",
                "export function loadConfig() {",
                "  return readFile('config.json');",
                "}",
                "const parseConfig = (input: string) => JSON.parse(input);",
                "router.get('/users/:id', loadConfig);",
                "export { parseConfig as parse } from './parse';",
                "router.post('/teams/:id', controller.getTeam);",
            ]
        )
        + "\n"
    )

    symbols = AstParser().parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert by_id["file:app.ts"].imports == ["./parse", "node:fs/promises"]
    assert by_id["file:app.ts"].exports == ["Loader", "Status", "UserDto", "loadConfig", "parse"]
    assert by_id["app.ts::UserDto"].type == "schema"
    assert by_id["app.ts::UserDto"].metadata["schema_kind"] == "interface"
    assert by_id["app.ts::Status"].type == "schema"
    assert by_id["app.ts::Loader"].type == "class"
    assert by_id["app.ts::Loader"].bases == ["BaseLoader"]
    assert by_id["app.ts::loadConfig"].type == "function"
    assert by_id["app.ts::parseConfig"].type == "function"
    endpoint = by_id["app.ts::endpoint:GET:/users/:id:9"]
    assert endpoint.type == "endpoint"
    assert endpoint.metadata["route_path"] == "/users/:id"
    member_endpoint = by_id["app.ts::endpoint:POST:/teams/:id:11"]
    assert member_endpoint.metadata["handler"] == "getTeam"
    assert member_endpoint.calls == ["getTeam"]


def test_registry_reports_supported_languages() -> None:
    parser = AstParser()

    assert "python" in parser.registry.supported_languages()
    assert "typescript" in parser.registry.supported_languages()
