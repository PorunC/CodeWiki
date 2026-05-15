from importlib import resources


def load_prompt(name: str) -> str:
    return resources.files("backend.app.prompts").joinpath(name).read_text(encoding="utf-8")
