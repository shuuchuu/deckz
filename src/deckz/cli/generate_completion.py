from typing import Literal

from .. import app_name
from . import app
from ._groups import SETUP


@app.command(group=SETUP)
def generate_completion(shell: Literal["zsh", "bash", "fish"]) -> None:
    """Generate a completion script so that you can install it manually.

    Args:
        shell: Type of shell for which to generate the completion script

    """
    print(app.generate_completion(prog_name=app_name, shell=shell))
