from pathlib import Path

from backend.app.config import get_settings
from backend.app.services.ast_parser import AstParser, AstParserRegistry, AstSymbol, parse_scanned_files
from backend.app.services.repo_scanner import RepoScanner
from backend.app.services.repo_scanner.file_info import sha256_file
from backend.app.services.source_file_cache import SourceFileContentProvider


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

    symbols = AstParser(cache_enabled=False).parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert "file:app.py" in by_id
    assert by_id["file:app.py"].imports == ["os", "pathlib.Path"]
    assert by_id["file:app.py"].metadata["tree_sitter_capture"] is True
    assert by_id["file:app.py"].metadata["language_enhancer"] == "python"
    assert by_id["app.py::Service"].type == "class"
    assert by_id["app.py::Service.run"].type == "method"
    assert "Path" in by_id["app.py::Service.run"].calls
    assert by_id["app.py::build"].type == "function"
    assert "Service" in by_id["app.py::build"].calls


def test_parse_scanned_files_parallel_preserves_results(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n")
    (tmp_path / "b.py").write_text("def beta():\n    return 2\n")
    scan = RepoScanner().scan(str(tmp_path))
    monkeypatch.setenv("CODEWIKI_AST_PARSE_WORKERS", "2")

    symbols, errors = parse_scanned_files(
        AstParser(cache_enabled=False),
        scan.files,
        repo_root=tmp_path,
    )

    assert errors == []
    assert [symbol.name for symbol in symbols if symbol.type == "function"] == ["alpha", "beta"]


def test_tree_sitter_typescript_parser_extracts_basic_symbols(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text(
        "\n".join(
            [
                "import { readFile } from 'node:fs/promises';",
                "export interface UserDto { id: string; name?: string }",
                "export interface Loadable { load(): Promise<string> }",
                "export type Status = 'ok' | 'bad';",
                "export class Loader extends BaseLoader implements Loadable {}",
                "export function loadConfig(): UserDto {",
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

    symbols = AstParser(cache_enabled=False).parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert by_id["file:app.ts"].imports == ["./parse", "node:fs/promises"]
    assert by_id["file:app.ts"].exports == ["Loadable", "Loader", "Status", "UserDto", "loadConfig", "parse"]
    assert by_id["file:app.ts"].metadata["language_enhancer"] == "ecma"
    assert by_id["app.ts::UserDto"].type == "schema"
    assert by_id["app.ts::UserDto"].metadata["schema_kind"] == "interface"
    assert by_id["app.ts::Loadable"].type == "schema"
    assert by_id["app.ts::Status"].type == "schema"
    assert by_id["app.ts::Loader"].type == "class"
    assert by_id["app.ts::Loader"].bases == ["BaseLoader"]
    assert by_id["app.ts::Loader"].implements == ["Loadable"]
    assert by_id["app.ts::loadConfig"].type == "function"
    assert "UserDto" in by_id["app.ts::loadConfig"].references
    assert by_id["app.ts::parseConfig"].type == "function"
    endpoint = by_id["app.ts::endpoint:GET:/users/:id:10"]
    assert endpoint.type == "endpoint"
    assert endpoint.metadata["route_path"] == "/users/:id"
    member_endpoint = by_id["app.ts::endpoint:POST:/teams/:id:12"]
    assert member_endpoint.metadata["handler"] == "getTeam"
    assert member_endpoint.calls == ["getTeam"]


def test_tree_sitter_javascript_parser_extracts_basic_symbols(tmp_path: Path) -> None:
    source = tmp_path / "app.js"
    source.write_text(
        "\n".join(
            [
                "import express from 'express';",
                "export class Loader extends Base {",
                "  run() { return fetchUser(); }",
                "}",
                "export function loadUser() {",
                "  return fetchUser();",
                "}",
                "const handler = () => loadUser();",
                "router.get('/users/:id', handler);",
            ]
        )
        + "\n"
    )

    symbols = AstParser(cache_enabled=False).parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert by_id["file:app.js"].imports == ["express"]
    assert by_id["file:app.js"].exports == ["Loader", "loadUser"]
    assert by_id["file:app.js"].metadata["language_enhancer"] == "ecma"
    assert by_id["app.js::Loader"].type == "class"
    assert by_id["app.js::Loader"].bases == ["Base"]
    assert by_id["app.js::Loader.run"].calls == ["fetchUser"]
    assert by_id["app.js::loadUser"].calls == ["fetchUser"]
    assert by_id["app.js::handler"].type == "function"
    endpoint = by_id["app.js::endpoint:GET:/users/:id:9"]
    assert endpoint.metadata["handler"] == "handler"
    assert endpoint.calls == ["handler"]


def test_tree_sitter_java_parser_extracts_symbols_imports_and_routes(tmp_path: Path) -> None:
    source = tmp_path / "src" / "main" / "java" / "com" / "example" / "UserController.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                "package com.example;",
                "",
                "import java.util.List;",
                "import org.springframework.web.bind.annotation.GetMapping;",
                "import org.springframework.web.bind.annotation.RequestMapping;",
                "",
                "@RestController",
                "@RequestMapping(\"/api\")",
                "public class UserController extends BaseController implements Handler {",
                "  private final UserService service;",
                "",
                "  public UserController(UserService service) {",
                "    this.service = service;",
                "  }",
                "",
                "  @GetMapping(\"/users/{id}\")",
                "  public UserDto getUser(String id) {",
                "    return service.loadUser(id);",
                "  }",
                "}",
                "",
                "record UserDto(String id) {}",
                "interface Handler { void handle(); }",
            ]
        )
        + "\n"
    )

    symbols = AstParser(cache_enabled=False).parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}
    file_id = "file:src/main/java/com/example/UserController.java"
    class_id = "src/main/java/com/example/UserController.java::UserController"

    assert by_id[file_id].imports == [
        "java.util.List",
        "org.springframework.web.bind.annotation.GetMapping",
        "org.springframework.web.bind.annotation.RequestMapping",
    ]
    assert by_id[file_id].exports == ["Handler", "UserController", "UserDto"]
    assert by_id[file_id].metadata["package"] == "com.example"
    assert by_id[file_id].metadata["language_enhancer"] == "java"
    assert by_id[class_id].type == "class"
    assert by_id[class_id].bases == ["BaseController"]
    assert by_id[class_id].implements == ["Handler"]
    assert by_id[class_id].decorators == ["RequestMapping", "RestController"]
    assert by_id[f"{class_id}.UserController"].type == "method"
    assert by_id[f"{class_id}.getUser"].type == "method"
    assert "loadUser" in by_id[f"{class_id}.getUser"].calls
    assert "UserDto" in by_id[f"{class_id}.getUser"].references
    assert by_id["src/main/java/com/example/UserController.java::UserDto"].type == "schema"
    assert by_id["src/main/java/com/example/UserController.java::Handler"].type == "interface"
    endpoint = by_id["src/main/java/com/example/UserController.java::endpoint:GET:/api/users/{id}:16"]
    assert endpoint.type == "endpoint"
    assert endpoint.metadata["route_path"] == "/api/users/{id}"
    assert endpoint.calls == ["getUser"]


def test_tree_sitter_go_parser_extracts_symbols_imports_methods_and_routes(tmp_path: Path) -> None:
    source = tmp_path / "cmd" / "api" / "main.go"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                "package api",
                "",
                "import (",
                "  \"context\"",
                "  alias \"example.com/project/pkg/service\"",
                ")",
                "",
                "type Server struct { svc *alias.Service }",
                "type Handler interface { Handle(ctx context.Context) error }",
                "type User = alias.User",
                "",
                "func NewServer(svc *alias.Service) *Server {",
                "  return &Server{svc: svc}",
                "}",
                "",
                "func (s *Server) GetUser(ctx context.Context, id string) (*User, error) {",
                "  return s.svc.LoadUser(ctx, id)",
                "}",
                "",
                "func registerRoutes(router *Router, server *Server) {",
                "  router.GET(\"/users/:id\", server.GetUser)",
                "}",
            ]
        )
        + "\n"
    )

    symbols = AstParser(cache_enabled=False).parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert by_id["file:cmd/api/main.go"].imports == ["context", "example.com/project/pkg/service"]
    assert by_id["file:cmd/api/main.go"].exports == ["Handler", "NewServer", "Server", "User"]
    assert by_id["file:cmd/api/main.go"].metadata["package"] == "api"
    assert by_id["file:cmd/api/main.go"].metadata["language_enhancer"] == "go"
    assert by_id["cmd/api/main.go::Server"].type == "class"
    assert by_id["cmd/api/main.go::Handler"].type == "interface"
    assert by_id["cmd/api/main.go::Handler.Handle"].type == "method"
    assert by_id["cmd/api/main.go::User"].type == "schema"
    assert by_id["cmd/api/main.go::NewServer"].type == "function"
    assert "Server" in by_id["cmd/api/main.go::NewServer"].references
    assert by_id["cmd/api/main.go::Server.GetUser"].type == "method"
    assert by_id["cmd/api/main.go::Server.GetUser"].parent_id == "cmd/api/main.go::Server"
    assert by_id["cmd/api/main.go::Server.GetUser"].calls == ["LoadUser"]
    endpoint = by_id["cmd/api/main.go::endpoint:GET:/users/:id:21"]
    assert endpoint.type == "endpoint"
    assert endpoint.metadata["handler"] == "GetUser"
    assert endpoint.calls == ["GetUser"]


def test_query_parser_extracts_rust_symbols_imports_methods_and_calls(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        "\n".join(
            [
                "use std::fmt;",
                "pub struct User { id: String }",
                "trait Loadable { fn load(&self) -> String; }",
                "impl User {",
                "  pub fn load(&self) -> String {",
                "    helper();",
                "    String::new()",
                "  }",
                "}",
                "fn helper() {}",
            ]
        )
        + "\n"
    )

    symbols = AstParser(cache_enabled=False).parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert by_id["file:src/lib.rs"].imports == ["std::fmt"]
    assert by_id["file:src/lib.rs"].exports == ["Loadable", "User", "helper"]
    assert by_id["file:src/lib.rs"].metadata["language_enhancer"] == "rust"
    assert by_id["src/lib.rs::User"].type == "class"
    assert by_id["src/lib.rs::Loadable"].type == "interface"
    assert by_id["src/lib.rs::Loadable.load"].type == "method"
    assert by_id["src/lib.rs::User.load"].parent_id == "src/lib.rs::User"
    assert "helper" in by_id["src/lib.rs::User.load"].calls
    assert by_id["src/lib.rs::helper"].type == "function"
    assert "src/lib.rs::load" not in by_id


def test_query_parser_extracts_c_symbols_imports_and_calls(tmp_path: Path) -> None:
    source = tmp_path / "main.c"
    source.write_text(
        "\n".join(
            [
                "#include <stdio.h>",
                "typedef struct User { int id; } User;",
                "int helper(void) { return 1; }",
                "int main(void) { return helper(); }",
            ]
        )
        + "\n"
    )

    symbols = AstParser(cache_enabled=False).parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert by_id["file:main.c"].imports == ["stdio.h"]
    assert by_id["file:main.c"].exports == ["User", "helper", "main"]
    assert by_id["file:main.c"].metadata["language_enhancer"] == "c"
    assert by_id["main.c::User"].type == "class"
    assert by_id["main.c::helper"].type == "function"
    assert by_id["main.c::main"].calls == ["helper"]


def test_query_parser_extracts_cpp_symbols_imports_methods_and_bases(tmp_path: Path) -> None:
    source = tmp_path / "app.cpp"
    source.write_text(
        "\n".join(
            [
                "#include <vector>",
                "class User : public Base { public: void load(); };",
                "void User::load() { helper(); }",
                "int helper() { return 1; }",
            ]
        )
        + "\n"
    )

    symbols = AstParser(cache_enabled=False).parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert by_id["file:app.cpp"].imports == ["vector"]
    assert by_id["file:app.cpp"].exports == ["User", "helper"]
    assert by_id["file:app.cpp"].metadata["language_enhancer"] == "cpp"
    assert by_id["app.cpp::User"].type == "class"
    assert by_id["app.cpp::User"].bases == ["Base"]
    assert by_id["app.cpp::User.load"].type == "method"
    assert by_id["app.cpp::User.load"].calls == ["helper"]
    assert by_id["app.cpp::helper"].type == "function"


def test_query_parser_extracts_csharp_symbols_imports_methods_and_calls(tmp_path: Path) -> None:
    source = tmp_path / "User.cs"
    source.write_text(
        "\n".join(
            [
                "using System;",
                "public interface ILoadable { void Load(); }",
                "public class User : Base, ILoadable {",
                "  public void Load() { Helper(); }",
                "  private void Helper() {}",
                "}",
            ]
        )
        + "\n"
    )

    symbols = AstParser(cache_enabled=False).parse_file(source, repo_root=tmp_path)
    by_id = {symbol.id: symbol for symbol in symbols}

    assert by_id["file:User.cs"].imports == ["System"]
    assert by_id["file:User.cs"].exports == ["ILoadable", "User"]
    assert by_id["file:User.cs"].metadata["language_enhancer"] == "csharp"
    assert by_id["User.cs::ILoadable"].type == "interface"
    assert by_id["User.cs::User"].type == "class"
    assert by_id["User.cs::User"].bases == ["Base", "ILoadable"]
    assert by_id["User.cs::User.Load"].type == "method"
    assert by_id["User.cs::User.Load"].calls == ["Helper"]
    assert by_id["User.cs::User.Helper"].type == "method"


def test_registry_reports_supported_languages() -> None:
    parser = AstParser()

    assert "c" in parser.registry.supported_languages()
    assert "cpp" in parser.registry.supported_languages()
    assert "csharp" in parser.registry.supported_languages()
    assert "go" in parser.registry.supported_languages()
    assert "java" in parser.registry.supported_languages()
    assert "python" in parser.registry.supported_languages()
    assert "rust" in parser.registry.supported_languages()
    assert "typescript" in parser.registry.supported_languages()


def test_ast_parser_caches_symbols_by_file_hash(tmp_path: Path) -> None:
    source = tmp_path / "cached.py"
    source.write_text("print('cached')\n")
    cache_dir = tmp_path / "cache" / "ast"
    language_parser = _CountingParser()
    registry = AstParserRegistry()
    registry.register(language_parser)
    parser = AstParser(registry=registry, cache_dir=cache_dir)

    first = parser.parse_file(source, repo_root=tmp_path)
    second = parser.parse_file(source, repo_root=tmp_path)

    assert first == second
    assert language_parser.parse_count == 1
    assert (cache_dir / f"{sha256_file(source)}.json").is_file()

    source.write_text("print('changed')\n")
    parser.parse_file(source, repo_root=tmp_path)

    assert language_parser.parse_count == 2


def test_ast_parser_uses_content_provider_for_parse_content(tmp_path: Path) -> None:
    source = tmp_path / "cached.py"
    source.write_text("print('cached')\n")
    provider = _CountingContentProvider(tmp_path)
    language_parser = _ContentParser()
    registry = AstParserRegistry()
    registry.register(language_parser)
    parser = AstParser(registry=registry, cache_enabled=False, content_provider=provider)

    parser.parse_file(source, repo_root=tmp_path)
    parser.parse_file(source, repo_root=tmp_path)

    assert provider.read_count == 1
    assert language_parser.contents == ["print('cached')\n", "print('cached')\n"]


def test_ast_parser_default_cache_uses_storage_cache_ast(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "default_cached.py"
    source.write_text("print('cached by default')\n")
    storage_dir = tmp_path / "storage"
    monkeypatch.setenv("CODEWIKI_STORAGE_DIR", str(storage_dir))
    get_settings.cache_clear()
    language_parser = _CountingParser()
    registry = AstParserRegistry()
    registry.register(language_parser)

    try:
        AstParser(registry=registry).parse_file(source, repo_root=tmp_path)
    finally:
        get_settings.cache_clear()

    assert (storage_dir / "cache" / "ast" / f"{sha256_file(source)}.json").is_file()


class _CountingParser:
    language = "python"

    def __init__(self) -> None:
        self.parse_count = 0

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        self.parse_count += 1
        return [
            AstSymbol(
                id=f"file:{path.relative_to(repo_root).as_posix() if repo_root else path.name}",
                type="file",
                name=path.name,
                file_path=path.relative_to(repo_root).as_posix() if repo_root else path.name,
                language=self.language,
                start_line=1,
                end_line=1,
                hash=str(self.parse_count),
            )
        ]


class _ContentParser:
    language = "python"

    def __init__(self) -> None:
        self.contents: list[str] = []

    def parse_content(
        self,
        path: Path,
        content: str,
        *,
        repo_root: Path | None = None,
    ) -> list[AstSymbol]:
        self.contents.append(content)
        return [
            AstSymbol(
                id=f"file:{path.relative_to(repo_root).as_posix() if repo_root else path.name}",
                type="file",
                name=path.name,
                file_path=path.relative_to(repo_root).as_posix() if repo_root else path.name,
                language=self.language,
                start_line=1,
                end_line=1,
            )
        ]

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        raise AssertionError("parse_content should be used when content provider is present")


class _CountingContentProvider(SourceFileContentProvider):
    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.read_count = 0

    def read_text(self, path: Path | str) -> str:
        key = self._cache_key(Path(path).resolve())
        if key not in self._texts:
            self.read_count += 1
        return super().read_text(path)
