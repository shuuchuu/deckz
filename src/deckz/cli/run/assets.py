from pathlib import Path

from . import app


@app.command(name="assets")
def run_assets(*, watch: bool = False, workdir: Path = Path()) -> None:
    """Build all the project standalones (images, tikz, plots, etc).

    Args:
        watch: Rebuild on file changes, instead of building once
        workdir: Path to move into before running the command

    """
    from ...pipelines import run_assets as _run_assets

    if not watch:
        _run_assets(workdir)
        return

    from ...components.factory import GlobalSettingsFactory
    from ...configuring.settings import GlobalSettings
    from ...pipelines import watch as _watch

    settings = GlobalSettings.from_yaml(workdir)
    assets_builder = GlobalSettingsFactory(settings).assets_builder()

    _watch(
        frozenset(assets_builder.watched_dirs()),
        frozenset([settings.paths.assets_dir]),
        _run_assets,
        workdir,
    )
