from functools import reduce
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ByteSize,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    model_validator,
)

from .. import app_name
from ..exceptions import InvalidConfigurationError
from ..models import SCHEMA_VERSION, Lang, SchemaVersion
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
    labs_published_dir: _Path = cast("Path", "{git_dir}/labs/published")
    labs_gpu_dir: _Path = cast("Path", "{git_dir}/.run/gpu")
    assets_lock: _Path = cast("Path", "{git_dir}/.run/assets.lock")
    scenes_dir: _Path = cast("Path", "{git_dir}/figures/scenes")
    videos_dir: _Path = cast("Path", "{assets_dir}/videos")
    templates_dir: _Path = cast("Path", "{git_dir}/templates")
    jinja2_dir: _Path = cast("Path", "{templates_dir}/jinja2")
    jinja2_main_template: _Path = cast("Path", "{jinja2_dir}/main.typ")
    jinja2_html_main_template: _Path = cast("Path", "{jinja2_dir}/main.html")
    jinja2_course_notes_main_template: _Path = cast(
        "Path", "{jinja2_dir}/course-notes.typ"
    )
    course_notes_dir: _Path = cast("Path", "{git_dir}/course-notes")
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
    course_notes_pdf_dir: _Path = cast("Path", "{pdf_dir}/course-notes")
    html_dir: _Path = cast("Path", "{current_dir}/html")
    local_content_dir: _Path = cast("Path", "{current_dir}/content")
    deck_definition: _Path = cast("Path", "{current_dir}/deck.yml")
    deck_path: Path = Field(
        default_factory=lambda data: data["current_dir"].relative_to(data["git_dir"])
    )
    """The deck's directory relative to the repository, the same in every \
    checkout: the key of what deckz keeps for it outside the repository."""
    drive_links: _Path = cast("Path", "{user_config_dir}/drive-links/{deck_path}.yml")


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
    worker processes as CPUs). The queue picks the least busy ones before \
    each notebook."""
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


class LabsOutputsHook(BaseModel):
    model_config = ConfigDict(frozen=True)
    run: tuple[str, ...]
    """Command to run from the git root (no shell), given the notebook's \
    path, relative to the git root, as its last argument. It edits the \
    notebook in place; deckz then writes it back in its canonical style."""
    notebooks: tuple[str, ...] = ()
    """Glob patterns (`**` for any directories), relative to \
    `paths.labs_notebooks_dir`, of the notebooks the hook runs on; unset, \
    every notebook."""


class LabsOutputsSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    hooks: dict[str, LabsOutputsHook] = Field(default_factory=dict)
    """Commands, by name, run in order on a notebook once `deckz labs \
    outputs` (or `deckz labs gpu pass --write-outputs`) wrote its outputs \
    back, e.g. to shrink what a library's outputs embed."""


class LabRepoSettings(BaseModel):
    """A lab whose project lives in a repository of its own.

    The lab's hands-on notebooks are its Colab version; the repository's \
    README, on the branch a trainee opens in their language, gives the same \
    statement for a GitHub Codespace or a local clone. `deckz labs repos` \
    reports where the branches and the READMEs drift from the notebooks.
    """

    model_config = ConfigDict(frozen=True)
    repo: str
    """The repository on GitHub, as `owner/name`."""
    lab: str
    """The lab, as a path under `paths.labs_notebooks_dir`: its notebooks \
    are `<lab>/hands-on-<lang>.ipynb` (and `demo-<lang>`), the hands-on ones \
    the README's Colab version."""
    url: str | None = None
    """Where `deckz labs repos` fetches it from; unset, \
    `https://github.com/<repo>.git`."""
    branches: dict[str, str | None] = Field(
        default_factory=lambda: {
            "main": None,
            "main-en": "main",
            "solution": "main",
            "solution-en": "solution",
        }
    )
    """Every branch, and the one it stacks on (none for the root): a branch \
    holds every commit of its base, so a change to the base is rebased into \
    it. The default is a starting point (`main`) and a solution, each with \
    its English translation."""
    start: dict[str, str] = Field(
        default_factory=lambda: {"fr": "main", "en": "main-en"}
    )
    """The branch a trainee opens, by language: its README is the lab's \
    statement in that language."""
    statement: bool = True
    """Whether those READMEs give the lab's statement yet. Until then, \
    `deckz labs repos` reports it, and a repository's templating can keep \
    the lab's links off the repository."""

    @model_validator(mode="after")
    def _known_branches(self) -> Self:
        unknown = sorted(
            {base for base in self.branches.values() if base is not None}.union(
                self.start.values()
            ).difference(self.branches)
        )
        if unknown:
            msg = f"labs.repos {self.repo}: {', '.join(unknown)} not in its branches"
            raise ValueError(msg)
        return self

    @property
    def fetch_url(self) -> str:
        return self.url or f"https://github.com/{self.repo}.git"


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
    published_files_remote: str | None = None
    """Git remote `deckz labs publish` force-pushes the files of \
    `paths.labs_published_dir` to, in a commit of their own (e.g. the \
    repository a Codespace opens, which holds no notebook); unset, they go \
    next to the notebooks, to `publish_remote`."""
    published_files_branch: str = "main"
    """Branch of `published_files_remote` that `deckz labs publish` replaces."""
    solution_heading: str = "Solution"
    """Markdown heading text (case-insensitive) marking a notebook's collapsed \
    answer cells, kept collapsed by `deckz labs normalize` and the \
    `deckz.labs.Notebook` library."""
    gpu: LabsGpuSettings = Field(default_factory=LabsGpuSettings)
    """Machines `deckz labs gpu` rents to run notebooks as Colab would."""
    outputs: LabsOutputsSettings = Field(default_factory=LabsOutputsSettings)
    """What `deckz labs outputs` does to a notebook after writing its outputs."""
    link_snippet: str | None = None
    """How a content file links a lab, printed by `deckz labs new` with \
    `{lab}` and `{kind}` filled in, e.g. \
    `{{ "{lab}" | lab("{kind}") }}` for a repository's own Jinja filter; \
    it may span several lines."""
    not_secrets: tuple[str, ...] = ()
    """Values the `lab-secrets` check (and `deckz labs publish`) would take \
    for a credential but aren't, e.g. a public dataset's read-only key."""
    repos: tuple[LabRepoSettings, ...] = ()
    """The labs with a repository of their own, which the `lab-urls` check \
    keeps content from linking by hand, and `deckz labs repos` reports on."""
    repo_link_hint: str | None = None
    """What the `lab-urls` check says to write instead of a hand-written \
    link to a lab's repository, with `{lab}` filled in, e.g. the call of a \
    repository's own Jinja filter."""

    @model_validator(mode="after")
    def _one_repo_per_lab(self) -> Self:
        labs = [repo.lab for repo in self.repos]
        if duplicates := sorted({lab for lab in labs if labs.count(lab) > 1}):
            msg = f"labs.repos: several repositories for {', '.join(duplicates)}"
            raise ValueError(msg)
        return self

    def repo_of(self, lab: str) -> LabRepoSettings | None:
        """The repository of `lab`, if it has one.

        Returns:
            Its settings, or None.
        """
        return next((repo for repo in self.repos if repo.lab == lab), None)


class I18nSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    synced_at: str | None = None
    """Commit (sha or any revision git resolves) up to which every fr/en \
    pair is known to be in sync, e.g. where a repository moved to \
    `Lang-sync` trailers from markers of its own.

    `deckz i18n stale` ignores that commit and its ancestors: they carry \
    no trailers, yet their one-sided changes were already settled."""


class ReviewSettings(BaseModel):
    """The review registry of `deckz review` (`deckz.analyzing.review`)."""

    model_config = ConfigDict(frozen=True)
    dir: str | None = None
    """Directory of the review reports, relative to the git root, e.g. \
    `docs/qa/sections`: every Markdown file under it, at any depth, is a \
    report, whose front matter's `reviewed` key deckz writes (`deckz review \
    mark`) and nothing else. Unset, `deckz review` refuses, and the \
    `review-headers` check and `deckz status` leave reviews alone."""


class ChecksSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    opt_in: tuple[str, ...] = ()
    """Checks `deckz check` runs only when named, e.g. `deckz check lab-outputs`.

    Built-in or plugin checks too slow, networked or not yet passing to \
    run on every commit (the pre-commit hook runs `deckz check --staged`, \
    i.e. every other check). They add to deckz's own opt-in checks \
    (`content_checks.OPT_IN`: `course-notes-code`, which runs the course \
    notes' code), which stay opt-in. A name no check has is ignored."""
    deferred: tuple[str, ...] | None = None
    """Checks whose findings `deckz check` prints without failing, unless named.

    Unset, deckz's built-in deferred checks (`content_checks.DEFERRED`: \
    those whose harm comes after the commit); a list replaces them, `[]` \
    making every check block a commit. A plugin check blocks unless listed. \
    A name no check has is ignored."""

    def runs_unnamed(self, name: str) -> bool:
        """Whether `deckz check`, run without naming checks, runs check `name`.

        Returns:
            True unless it's opt-in.
        """
        from ..analyzing.content_checks import OPT_IN

        return name not in OPT_IN and name not in self.opt_in

    def blocking(self, name: str) -> bool:
        """Whether a finding of check `name` fails `deckz check` run unnamed.

        Returns:
            True unless it's deferred.
        """
        from ..analyzing.content_checks import DEFERRED

        return name not in (DEFERRED if self.deferred is None else self.deferred)


class DatasetsSettings(BaseModel):
    """The repository holding the data sets course notes chapters read.

    A chapter links each file or directory it reads to that repository \
    (`<url>/raw/refs/heads/main/<path>` for a file, `<url>/tree/main/<path>` \
    for a directory, or `bash /tmp/ghsparse.sh <directory>`, the sparse \
    clone script the repository serves): `deckz check course-notes-code` \
    puts each in the chapter's working directory under the name a download \
    gives it, from a local clone, and `deckz setup` reports that clone \
    missing or behind its upstream.
    """

    model_config = ConfigDict(frozen=True)
    url: str
    """Its web address (`https://github.com/<owner>/<repository>`)."""
    path: str = "{git_dir}/../datasets"
    """Its local clone; `{git_dir}` stands for the repository's root."""


class CourseNotesCodeSettings(BaseModel):
    """How `deckz check course-notes-code` runs the chapters' Python code.

    Each chapter runs in a process of its own, in a scratch working \
    directory, its `pycon` sessions, `python` blocks and `console` commands \
    compared with the outputs it shows (see `deckz.code_runner`).
    """

    model_config = ConfigDict(frozen=True)
    python: tuple[str, ...] = ()
    """The command running Python with the libraries the chapters use, at \
    the versions their labs use; deckz adds the runner script and its \
    arguments. `{git_dir}` stands for the repository's root, and an element \
    `{with}` for `--with <package>` for each of the chapter's \
    `requirements` (or for nothing), e.g. `[uv, run, --no-project, \
    --with-requirements, "{git_dir}/requirements.txt", "{with}", python]`. \
    Unset, deckz's own interpreter."""
    timeout: int = 30
    """Seconds one example may run (a `pycon` prompt, a `python` block, a \
    console command)."""
    jobs: int = 4
    """Chapters run at the same time. Each loads its libraries and data: \
    lower it for chapters with big data sets."""
    setup: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    """What chapters need before their own code: `<pattern>: [<path>...]`. \
    The patterns match chapters' paths relative to the course notes \
    directory, without extension nor `en/`, as `PurePosixPath.full_match` \
    reads them (`python/pandas/**`). The paths, relative to the repository's \
    root, are chapters, whose code runs first, in the same namespace, its \
    outputs unchecked (an English chapter runs the setup chapter's English \
    version when there is one), or other files, linked into the working \
    directory (a data set the examples read)."""
    requirements: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    """The packages chapters need beyond `python`'s: `<pattern>: \
    [<requirement>...]`, the patterns as `setup`'s (`python/web/flask/**: \
    [flask >= 3, < 4]`), passed to `python` where its `{with}` stands."""
    commands: tuple[str, ...] = ()
    """The programs a ```` ```console ```` block may run (`python`, \
    `pytest`, `ruff`): its commands run, their outputs compared, only when \
    each program it runs is listed. Leave out those changing a project or \
    reaching outside the machine (`uv add`, `git push`)."""
    datasets: DatasetsSettings | None = None
    """The data sets repository chapters link to, if any."""


class CourseNotesSettings(BaseModel):
    """A deck's course notes, built by `deckz run course-notes`.

    A deck's written-out reference, one chapter per content file: the chapter \
    of `<content_dir>/<path>.md` is `<course_notes_dir>/<path>.md`, its \
    English version `en/<same name>` next to it, like content's (see \
    `deckz.course_notes`).
    """

    model_config = ConfigDict(frozen=True)
    skip: tuple[str, ...] = ()
    """Content files that have no chapter, on purpose (a deck's practical \
    information, lab frames, quizzes): patterns on their paths relative to \
    the content directory, without extension, as `PurePosixPath.full_match` \
    reads them (`about/**`, `**/quiz-*`). A chapter written for one is used \
    all the same: these only keep it from being reported missing."""
    same_as: dict[str, str] = Field(default_factory=dict)
    """Content files another one's chapter covers (a short variant of a \
    file): `<path>: <path of the file whose chapter covers it>`, both \
    relative to the content directory, without extension."""
    suffix: str = "course-notes"
    """What a deck's course notes PDF is named after: `<deck>-<suffix>.pdf`, \
    in `paths.course_notes_pdf_dir`."""
    code: CourseNotesCodeSettings = Field(default_factory=CourseNotesCodeSettings)
    """How `deckz check course-notes-code` runs the chapters' code."""


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


class SetupRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)
    command: str
    """Executable that must be on the `PATH`."""
    why: str
    """What needs it, shown when it's missing."""
    install: str | None = None
    """How to install it, e.g. `apt install poppler-utils`."""


class SetupStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    """What the step does, shown in `deckz setup`'s report."""
    run: tuple[str, ...]
    """Command to run, from the git root (no shell)."""
    creates: str | None = None
    """Path, relative to the git root, the step creates: when it exists, \
    the step is done and skipped (`deckz setup --force` runs it anyway)."""
    check: tuple[str, ...] | None = None
    """Command, from the git root (no shell), that exits 0 when the step is \
    done, e.g. `[uv, sync, --check]`: then the step is skipped, as with \
    `creates` (both must hold when both are given). What `deckz setup \
    --check` runs to tell. Without `creates` nor `check`, the step runs \
    every time, and `--check` can only report it as to run."""


class SetupSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    requires: tuple[SetupRequirement, ...] = ()
    """Executables the repository needs besides deckz's own (pandoc, git)."""
    steps: tuple[SetupStep, ...] = ()
    """Commands that set up a clone or a worktree, e.g. `uv sync` (its \
    `check`: `uv sync --check`) or vendoring JavaScript (its `creates`: the \
    vendor directory)."""
    remotes: dict[str, str] = Field(default_factory=dict)
    """Git remotes a clone needs besides `origin`, by name: their URLs, e.g. \
    `labs: git@github.com:owner/labs.git` for the remotes `deckz labs \
    publish` and `deckz videos publish` push to. `deckz setup` adds the \
    missing ones, and leaves one already there alone, whatever its URL."""


class WorktreeSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    seed: tuple[str, ...] = ()
    """Paths, relative to the git root, whose ignored files (the builds a \
    fresh checkout lacks, e.g. rendered figures and videos) `deckz worktree \
    add` copies from the main checkout into a new worktree."""
    required_for_agents: bool = False
    """Whether a Claude Code session changes the repository only from a \
    worktree: deckz's hooks then deny it any change in the main checkout, \
    which every session shares (see `deckz.agent_checkouts`)."""


class CiSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    deckz_repository: str | None = None
    """GitHub repository (`owner/name`) of the deckz the repository installs \
    from a sibling checkout (a uv path dependency on `../deckz`): the workflow \
    checks it out next to the repository. Unset: deckz comes from the index."""
    deckz_ref: str = "main"
    """Branch, tag or commit of `deckz_repository` to check out."""
    apt_packages: tuple[str, ...] = ()
    """Debian packages the repository's dependencies need to install, e.g. \
    `libcairo2-dev` and `pkg-config` to build pycairo."""
    nightly_checks: tuple[str, ...] = ()
    """Checks too slow for every push (usually some of `checks.opt_in`), run \
    every night, e.g. `missing-en`."""
    builds: tuple[Lang, ...] = ()
    """Languages a scheduled job builds the handouts of the decks the \
    period's commits reach in (`deckz run decks --since`), so a deck broken \
    by a change to shared content shows before it's taught; none, no build. \
    The image has the toolchain deckz needs (pandoc, poppler); \
    `apt_packages` adds the repository's assets builders'."""
    builds_schedule: Literal["weekly", "nightly"] = "weekly"
    """When `builds` run: `weekly` (Sundays at 04:00 UTC, the decks the last \
    7 days' commits reach) or `nightly` (every night, the last day's). A \
    build reaching every deck takes about 45 runner minutes on a large \
    repository, which a private one pays for."""
    videos_repository: str | None = None
    """GitHub repository (`owner/name`) the videos are published to, which \
    the scheduled builds fetch the renders from first (`deckz videos fetch`): \
    a deck showing a video needs its render."""
    user_variables: dict[str, Any] = Field(default_factory=dict)
    """Written as the CI machine's own `variables.yml` (deckz's user config \
    directory) before the scheduled builds: what each person's own file sets \
    (a trainer's name, an email), which a template may need to render, \
    with stand-in values."""
    report_to: tuple[str, ...] = ()
    """GitHub logins a scheduled run's problems are reported to: an issue \
    labeled `deckz-ci` mentioning and assigning them, which GitHub emails \
    them, written to be pasted to an agent (`deckz hooks ci-report`); a \
    comment on it while it's open. None: the run only fails."""
    cache_paths: tuple[str, ...] = ()
    """Directories, relative to the repository's root, of what the scheduled \
    builds generate and keep from one build to the next (`actions/cache`), \
    e.g. the assets builders' outputs, which are only rebuilt when stale: \
    built from nothing, they can take longer than the decks. Never a \
    directory holding committed files, which a restore would overwrite."""


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
    typst_machine_compilations: int | None = Field(default=None, ge=1)
    """How many Typst compilations may run at once on this machine, across \
    every deckz process of the user: builds in other checkouts and \
    worktrees, a `--watch` next to an agent's build.

    `typst_parallel_compilations` only bounds one process. A compilation \
    waits for a slot (saying so once) while they're all taken. Machine-wide \
    by nature, so the user's own `deckz.yml` is the place to set it, or a \
    repository's as a default. Unset: no machine-wide limit.
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
    line_marker_label: str = "formation-line"
    """Typst label `deckz check overflow` queries for lines that wrap.

    The target repo's Typst theme emits one `<label>` metadata value per \
    page whose header or footer line, meant to fit on one line, wraps: \
    `page`, `line` (which one, e.g. `footer`), `text` (its plain text), \
    `ratio` (its width over its room, as a percentage), `fix` (what to \
    shorten, in the repo's terms) and, optionally, `frame` (true when \
    that's in the page's frame, whose `# Title` line is then reported); \
    the check itself stays the theme's.
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
    review: ReviewSettings = Field(default_factory=ReviewSettings)
    """Where `deckz review`'s reports are."""
    videos: VideosSettings = Field(default_factory=VideosSettings)
    course_notes: CourseNotesSettings = Field(default_factory=CourseNotesSettings)
    setup: SetupSettings = Field(default_factory=SetupSettings)
    """What `deckz setup` checks and runs on top of deckz's own needs."""
    worktree: WorktreeSettings = Field(default_factory=WorktreeSettings)
    """What `deckz worktree add` brings into a new worktree."""
    ci: CiSettings = Field(default_factory=CiSettings)
    """What `deckz hooks install --ci`'s workflow runs and needs."""
    paths: GlobalPaths

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
    paths: DeckPaths

    def with_output_dirs(self, build_dir: Path, pdf_dir: Path, html_dir: Path) -> Self:
        """Copy of these settings writing to other build and output directories.

        Args:
            build_dir: Absolute path of the new build directory.
            pdf_dir: Absolute path of the new PDF directory.
            html_dir: Absolute path of the new HTML directory.

        Returns:
            The copy. These settings are left untouched. The course notes' \
            PDF directory moves with the PDF one when it's under it (by \
            default), else to its `course-notes/`.
        """
        old_pdf_dir, notes_dir = self.paths.pdf_dir, self.paths.course_notes_pdf_dir
        notes_dir = pdf_dir / (
            notes_dir.relative_to(old_pdf_dir)
            if notes_dir.is_relative_to(old_pdf_dir)
            else "course-notes"
        )
        paths = self.paths.model_copy(
            update={
                "build_dir": build_dir,
                "pdf_dir": pdf_dir,
                "course_notes_pdf_dir": notes_dir,
                "html_dir": html_dir,
            }
        )
        return self.model_copy(update={"paths": paths})
