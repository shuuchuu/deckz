from jinja2 import Environment


def environment_for(suffix: str) -> Environment:
    if suffix == ".md":
        # Plain Jinja delimiters read fine in Markdown -- no need for the
        # LaTeX-escaped scheme legacy .tex sources use.
        return Environment(autoescape=False)
    return Environment(
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
