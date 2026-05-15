def normalize_import(value: str) -> str:
    text = value.strip().rstrip(";")
    if text.startswith(("<", '"', "'")) and text.endswith((">", '"', "'")):
        text = text[1:-1]
    return text.strip()


def normalize_identifier(value: str) -> str:
    text = value.strip().strip("&*")
    text = text.removeprefix("::")
    text = text.replace("this.", "").replace("self.", "")
    for delimiter in ("::", ".", "->"):
        if delimiter in text:
            text = text.rsplit(delimiter, 1)[-1]
    return text.strip()


def signature_text(node, language: str) -> str:
    text = node.text.decode("utf-8", errors="replace").strip()
    if "{" in text:
        return text.split("{", 1)[0].strip()
    if language == "rust" and ";" in text:
        return text.split(";", 1)[0].strip()
    return text
