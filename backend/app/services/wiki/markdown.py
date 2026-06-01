import re

MERMAID_FENCE_RE = re.compile(r"```mermaid.*?```", re.DOTALL | re.IGNORECASE)
CONJOINED_FENCE_HEADING_RE = re.compile(r"(?m)^([ \t]*`{3,})[ \t]*(#{1,6}[ \t]+)")
REQUIRED_PAGE_HEADINGS = ("## Purpose and Scope",)

def _strip_llm_mermaid(markdown: str) -> str:
    return MERMAID_FENCE_RE.sub("", markdown).strip()


def _repair_conjoined_fence_headings(markdown: str) -> str:
    return CONJOINED_FENCE_HEADING_RE.sub(r"\1\n\2", markdown)


def _validate_page_markdown(markdown: str, expected_title: str) -> list[str]:
    errors: list[str] = []
    stripped = markdown.strip()
    if not stripped.startswith("# "):
        errors.append("markdown must start with an H1 title.")
    if expected_title and f"# {expected_title}" not in stripped.splitlines()[:3]:
        errors.append(f"markdown H1 must match page title: {expected_title}.")
    for heading in REQUIRED_PAGE_HEADINGS:
        if heading not in stripped:
            errors.append(f"markdown must include required heading: {heading}.")
    return errors

