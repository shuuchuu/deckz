from jinja2 import Environment


def environment_for(suffix: str) -> Environment:
    return Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)
