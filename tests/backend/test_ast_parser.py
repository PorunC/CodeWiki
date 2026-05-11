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


def test_javascript_like_parser_extracts_basic_symbols(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text(
        "\n".join(
            [
                "import { readFile } from 'node:fs/promises';",
                "export class Loader {}",
                "export function loadConfig() {",
                "  return readFile('config.json');",
                "}",
                "const parseConfig = (input: string) => JSON.parse(input);",
            ]
        )
        + "\n"
    )

    symbols = AstParser().parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert by_id["file:app.ts"].imports == ["node:fs/promises"]
    assert by_id["app.ts::Loader"].type == "class"
    assert by_id["app.ts::loadConfig"].type == "function"
    assert by_id["app.ts::parseConfig"].type == "function"


def test_registry_reports_supported_languages() -> None:
    parser = AstParser()

    assert "python" in parser.registry.supported_languages()
    assert "typescript" in parser.registry.supported_languages()
