from functools import reduce
from pathlib import Path
from typing import Annotated, Any, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ByteSize,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
)

from .. import app_name
from ..exceptions import InvalidConfigurationError
from ..models import SCHEMA_VERSION, SchemaVersion
from ..utils import dirs_hierarchy, get_git_dir, load_all_yamls


def _convert(input_value: str | Path, info: ValidationInfo) -> Path:
    if isinstance(input_value, str):
        return Path(input_value.format(**info.data))
    return input_value


_Path = Annotated[Path, BeforeValidator(_convert), AfterValidator(Path.resolve)]


def default_user_config_dir() -> Path:
    """The user's XDG config directory for deckz, looked up on each call.

    Returns:
        The directory. It may not exist.
    """
    import appdirs

    return Path(appdirs.user_config_dir(app_name)).resolve()


# ruff: file-ignore[missing-f-string-syntax]
class GlobalPaths(BaseModel):
    model_config = ConfigDict(validate_default=True, frozen=True)
    current_dir: _Path
    user_config_dir: _Path = Field(default_factory=default_user_config_dir)
    git_dir: _Path = Field(
        default_factory=lambda data: get_git_dir(data["current_dir"])
    )
    settings: _Path = cast("Path", "{git_dir}/settings.yml")
    assets_dir: _Path = cast("Path", "{git_dir}/assets")
    content_dir: _Path = cast("Path", "{git_dir}/content")
    labs_notebooks_dir: _Path = cast("Path", "{git_dir}/labs/notebooks")
    labs_gpu_dir: _Path = cast("Path", "{git_dir}/.run/gpu")
    scenes_dir: _Path = cast("Path", "{git_dir}/figures/scenes")
    videos_dir: _Path = cast("Path", "{assets_dir}/videos")
    templates_dir: _Path = cast("Path", "{git_dir}/templates")
    jinja2_dir: _Path = cast("Path", "{templates_dir}/jinja2")
    jinja2_main_template: _Path = cast("Path", "{jinja2_dir}/main.typ")
    jinja2_html_main_template: _Path = cast("Path", "{jinja2_dir}/main.html")
    jinja2_env_module: _Path = cast("Path", "{jinja2_dir}/env.py")
    assets_builders_module: _Path = cast("Path", "{templates_dir}/assets_builders.py")
    checks_module: _Path = cast("Path", "{templates_dir}/checks.py")
    hooks_module: _Path = cast("Path", "{templates_dir}/hooks.py")
    github_issues: _Path = cast("Path", "{user_config_dir}/github-issues.yml")
    mails: _Path = cast("Path", "{user_config_dir}/mails.yml")
    gdrive_secrets: _Path = cast("Path", "{user_config_dir}/gdrive-secrets.json")
    gdrive_credentials: _Path = cast(
        "Path", "{user_config_dir}/gdrive-credentials.pickle"
    )


class DeckPaths(GlobalPaths):
    build_dir: _Path = cast("Path", "{current_dir}/.build")
    pdf_dir: _Path = cast("Path", "{current_dir}/pdf")
    html_dir: _Path = cast("Path", "{current_dir}/html")
    local_content_dir: _Path = cast("Path", "{current_dir}/content")
    deck_definition: _Path = cast("Path", "{current_dir}/deck.yml")


class LabsGpuSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    image: str = "us-docker.pkg.dev/colab-images/public/runtime"
    """Docker image the rented machine boots: Colab's own runtime by default \
    (the one Colab's local runtimes use), so the packages are Colab's."""
    gpus: tuple[str, ...] = ("Tesla_T4", "RTX_A4000")
    """GPU names `deckz labs gpu up` rents, the first one on offer winning.

    A T4 is Colab's free GPU; any other runs faster than Colab does."""
    offer_filter: str = (
        "num_gpus=1 reliability>0.98 cpu_ram>=12 disk_space>=100 "
        "cuda_max_good>=12.4 rentable=true verified=true"
    )
    """Vast.ai offer query, on top of the GPU name (`vastai search offers`): \
    Colab's T4 runtime has 12.7 GB of RAM, and its image needs a recent CUDA \
    driver."""
    disk_gb: int = 100
    """Disk size of the rented machine, in GB."""
    boot_minutes: int = 30
    """How long a machine may take to pull the image and start before it is \
    destroyed and another one rented."""
    cpus: int = 2
    """CPUs each notebook runs on (Colab's T4 runtime has 2): hosts expose \
    dozens, which hides what Colab would hit (e.g. a deadlock with as many \
    worker processes as CPUs)."""
    ssh_key: str = "~/.ssh/id_ed25519"
    """Private SSH key whose public key is registered with Vast.ai \
    (`vastai create ssh-key`)."""
    fresh_dirs: tuple[str, ...] = ("/usr/local",)
    """Directories `up` copies once the machine booted, before any notebook \
    runs, and the queue restores before each one, so every notebook starts \
    from the image's state, as on a fresh Colab VM, whatever the ones before \
    it installed or removed (pip installs into `/usr/local`)."""
    metadata_key: str = "shuuchuu.gpu"
    """Dotted path, under a notebook's own `metadata`, of what its runs need.

    `variables` and `secrets` each map a variable of the notebook, assigned \
    `""` on a line of its own, to the environment variable (or `.env` entry) \
    `deckz labs gpu queue` fills it from in the copy it sends; a secret's \
    value is also redacted from what `fetch` copies back, and `deckz labs \
    outputs` stores no output that showed it. `hook` names one of `hooks`."""
    hooks: dict[str, str] = Field(default_factory=dict)
    """Shell commands, by name, run from the repository's root before a \
    notebook naming one is queued and once its run is done, e.g. to reset a \
    server the notebook writes to. Notebooks naming the same hook run one at \
    a time, across machines: the next one is held until then."""


class LabsSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    id_metadata_key: str = "shuuchuu.id"
    """Dotted path, under a notebook's own `metadata`, of its published ID.

    `deckz labs ids`/`deckz labs publish` read and write it."""
    id_pattern: str = r"[a-z0-9]+(-[a-z0-9]+)*"
    """Regex a notebook's published ID must fully match."""
    publish_remote: str = "labs"
    """Git remote `deckz labs publish` force-pushes the published notebooks to."""
    publish_branch: str = "main"
    """Branch of `publish_remote` that `deckz labs publish` replaces."""
    solution_heading: str = "Solution"
    """Markdown heading text (case-insensitive) marking a notebook's collapsed \
    answer cells, kept collapsed by `deckz labs normalize` and the \
    `deckz.labs.Notebook` library."""
    gpu: LabsGpuSettings = Field(default_factory=LabsGpuSettings)
    """Machines `deckz labs gpu` rents to run notebooks as Colab would."""


class I18nSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    synced_at: str | None = None
    """Commit (sha or any revision git resolves) up to which every fr/en \
    pair is known to be in sync, e.g. where a repository moved to \
    `Lang-sync` trailers from markers of its own.

    `deckz i18n stale` ignores that commit and its ancestors: they carry \
    no trailers, yet their one-sided changes were already settled."""


class ChecksSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    opt_in: tuple[str, ...] = ()
    """Checks `deckz check` runs only when named, e.g. `deckz check lab-outputs`.

    Built-in or plugin checks too slow, networked or not yet passing to \
    run on every commit (the pre-commit hook runs `deckz check --staged`, \
    i.e. every other check). A name no check has is ignored."""


class VideosSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    publish_remote: str = "videos"
    """Git remote `deckz videos publish` force-pushes the published renders to."""
    publish_branch: str = "main"
    """Branch of `publish_remote` that `deckz videos publish` replaces."""
    published_quality: str = "h"
    """Manim quality flag (`l`, `m`, `h`, `p` or `k`) a render must be at to publish.

    Also `deckz videos render`'s default `--quality`."""
    max_publish_size_mb: int = 100
    """Refuse to publish a render over this size, in MB (GitHub's own limit)."""
    warn_publish_size_mb: int = 50
    """Warn, but still publish, a render over this size, in MB."""


class GlobalSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: SchemaVersion = SCHEMA_VERSION
    """Version of the `deckz.yml` format."""
    typst_parallel_compilations: int = Field(default=1, ge=1)
    """How many Typst compilations (one per PDF) may run at once.

    Each one can take a few GB on a large deck, and Typst already uses every \
    core within a single compilation, so more than 1 mostly trades memory for \
    a small speedup.
    """
    typst_memory_max: ByteSize | None = None
    """Stop a Typst compilation whose process uses more memory than this.

    E.g. `5GiB`. The PDF then fails to build, with a message naming the \
    limit, instead of the machine running out of memory on a large deck. \
    Checked every half second, on Linux only. Unset: no limit.
    """
    typst_font_paths: tuple[str, ...] = ()
    """Directories Typst searches for fonts, on top of its embedded ones.

    Relative to the git root; `{git_dir}`, `{assets_dir}` and \
    `{templates_dir}` are substituted.
    """
    typst_ignore_system_fonts: bool = False
    """Don't let Typst use the system's fonts.

    Builds then only depend on `typst_font_paths` and Typst's embedded \
    fonts, identical on every machine, and each PDF skips a system font scan.
    """
    overflow_marker_label: str = "formation-overflow"
    """Typst label `deckz check overflow` queries for shrunk-to-fit frames.

    The target repo's Typst theme emits one `<label>` metadata value per \
    frame it had to shrink to fit the page, with `ratio` and `page` keys; \
    this setting is only the label's name, not the shrinking mechanism \
    itself, which stays entirely the theme's business.
    """
    table_marker_label: str = "formation-table"
    """Typst label `deckz check overflow --tables` queries for tables.

    The target repo's Typst theme emits one `<label>` metadata value per \
    table, with `page`, `wrap` (the table's height over its height with no \
    cell wrapped, as a percentage) and `overflow` (whether its longest words \
    alone are wider than the frame) keys; the table layout itself stays \
    the theme's.
    """
    pandoc_command: tuple[str, ...] = ()
    """Command converting a rendered Markdown fragment to Typst.

    deckz appends the fragment's name and `-o <output>`, and runs it from \
    the fragment's directory. `{git_dir}` and `{templates_dir}` are \
    substituted.
    """
    html_pandoc_command: tuple[str, ...] = ()
    """Same as `pandoc_command`, converting to HTML for `--html` builds, \
    whose main template is `paths.jinja2_html_main_template`."""
    html_static_dirs: tuple[str, ...] = ()
    """Directories of the build directory (i.e. of `assets/`) copied whole \
    into every HTML output, on top of the files its page references.

    For files only scripts load, which packaging can't find by itself, e.g. \
    a math renderer's fonts and extensions.
    """
    file_extensions: tuple[str, ...] = (".md",)
    labs: LabsSettings = Field(default_factory=LabsSettings)
    checks: ChecksSettings = Field(default_factory=ChecksSettings)
    i18n: I18nSettings = Field(default_factory=I18nSettings)
    videos: VideosSettings = Field(default_factory=VideosSettings)
    paths: GlobalPaths = Field(default_factory=GlobalPaths)

    @classmethod
    def from_yaml(cls, path: Path, *, git_dir: Path | None = None) -> Self:
        """Load the settings in effect at `path`, merging every `deckz.yml` above.

        Args:
            path: Directory to load the settings for, e.g. a deck's.
            git_dir: Root of the repository containing `path`, when the \
                caller already knows it (e.g. while walking every deck), to \
                skip discovering it again.

        Returns:
            The settings.

        Raises:
            InvalidConfigurationError: If a `deckz.yml` is invalid.
        """
        resolved_path = path.resolve()
        git_dir = (get_git_dir(resolved_path) if git_dir is None else git_dir).resolve()
        user_config_dir = default_user_config_dir()
        content: dict[str, Any] = reduce(
            lambda a, b: {**a, **b},
            load_all_yamls(
                d
                for p in dirs_hierarchy(git_dir, user_config_dir, resolved_path)
                if (d := p / "deckz.yml").is_file()
            ),
            {},
        )
        # Pass what was just discovered rather than letting validation look
        # it up again.
        paths = content.setdefault("paths", {})
        paths.setdefault("current_dir", path)
        paths.setdefault("git_dir", git_dir)
        paths.setdefault("user_config_dir", user_config_dir)
        try:
            return cls.model_validate(content)
        except ValidationError as e:
            msg = f"invalid deckz.yml settings:\n{e}"
            raise InvalidConfigurationError(msg) from e


class DeckSettings(GlobalSettings):
    paths: DeckPaths = Field(default_factory=DeckPaths)

    def with_output_dirs(self, build_dir: Path, pdf_dir: Path, html_dir: Path) -> Self:
        """Copy of these settings writing to other build and output directories.

        Args:
            build_dir: Absolute path of the new build directory.
            pdf_dir: Absolute path of the new PDF directory.
            html_dir: Absolute path of the new HTML directory.

        Returns:
            The copy. These settings are left untouched.
        """
        paths = self.paths.model_copy(
            update={"build_dir": build_dir, "pdf_dir": pdf_dir, "html_dir": html_dir}
        )
        return self.model_copy(update={"paths": paths})
