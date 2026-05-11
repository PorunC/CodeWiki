from pathlib import Path

from backend.app.services.language_detector import LanguageDetector


def test_detects_language_by_extension_and_filename() -> None:
    detector = LanguageDetector()

    assert detector.detect(Path("src/main.py")) == "python"
    assert detector.detect(Path("src/App.tsx")) == "tsx"
    assert detector.detect(Path("Dockerfile")) == "dockerfile"
    assert detector.detect(Path("unknown.nope")) == "unknown"


def test_source_language_flag() -> None:
    detector = LanguageDetector()

    assert detector.is_source_language("python") is True
    assert detector.is_source_language("markdown") is False
