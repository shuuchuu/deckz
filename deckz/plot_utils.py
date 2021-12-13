from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("PDF")

import matplotlib.pyplot as plt  # noqa: E402

from deckz.paths import GlobalPaths  # noqa: E402


# This method is not used directly, instead we give a specific save method for each
# Python file, created with _create_tailored_save_function and patched into the save
# name. It is left here so that imports don't complain
def save(name: str = None) -> None:
    pass


def _create_tailored_save_function(
    paths: GlobalPaths, python_file: Path
) -> Callable[[Callable[[], None], str], None]:
    name = python_file.with_suffix("").name
    output_dir = (
        paths.shared_plt_pdf_dir / python_file.relative_to(paths.shared_plt_dir).parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    def save(function: Callable[[], None], suffix: str = "") -> None:
        dashed_suffix = f"-{suffix}" if suffix else ""
        output_path = output_dir / f"{name}{dashed_suffix}.pdf"
        if (
            not output_path.exists()
            or output_path.stat().st_mtime_ns < python_file.stat().st_mtime_ns
        ):
            function()
            plt.savefig(output_path, bbox_inches="tight")

    return save
