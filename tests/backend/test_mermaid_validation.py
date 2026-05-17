from backend.app.services.wiki.diagrams.rendering import _mermaid_class_text
from backend.app.services.wiki.mermaid_validation import validate_mermaid, validate_mermaid_blocks


def test_validate_mermaid_accepts_supported_diagram() -> None:
    assert validate_mermaid("flowchart TD\n  A --> B") is None


def test_validate_mermaid_rejects_invalid_diagram() -> None:
    error = validate_mermaid("flowchart TD\n  A -->")

    assert error is not None
    assert "Parse error" in error


def test_class_text_sanitizes_python_type_annotations() -> None:
    diagram = "\n".join(
        [
            "classDiagram",
            "  class A",
            f"  A : +{_mermaid_class_text('(x: int) -> str')}",
        ]
    )

    assert validate_mermaid(diagram) is None


def test_validate_mermaid_blocks_reports_block_index() -> None:
    markdown = "\n".join(
        [
            "# Page",
            "",
            "```mermaid",
            "flowchart TD",
            "  A --> B",
            "```",
            "",
            "```mermaid",
            "flowchart TD",
            "  A -->",
            "```",
        ]
    )

    errors = validate_mermaid_blocks(markdown)

    assert len(errors) == 1
    assert errors[0].startswith("Mermaid block 2:")
    assert "Parse error" in errors[0]
