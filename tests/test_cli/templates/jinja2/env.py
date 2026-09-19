from jinja2 import Environment

from deckz.models import Title


def _to_camel_case(string: str) -> str:
    return "".join(substring.capitalize() or "_" for substring in string.split("_"))


def _is_title(value: object) -> bool:
    return isinstance(value, Title)


def environment_for(suffix: str) -> Environment:
    env = Environment(
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\V{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        line_statement_prefix="%%",
        line_comment_prefix="%#",
        trim_blocks=True,
        autoescape=False,
    )
    env.filters["camelcase"] = _to_camel_case
    env.tests["title"] = _is_title
    return env
