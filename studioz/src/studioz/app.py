"""The web application: pages over a deckz repository's workspaces."""

import asyncio
import json
import subprocess
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from functools import partial
from importlib.resources import files
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup
from starlette.datastructures import UploadFile

from deckz.analyzing.frames import frames
from deckz.analyzing.i18n_stale import lang_sync_kind, one_sided
from deckz.configuring.settings import DeckSettings, GlobalSettings
from deckz.exceptions import DeckzError, WorktreeError
from deckz.models import LANGS, Lang
from deckz.worktrees import main_checkout, remove

from . import (
    __version__,
    actions,
    agent,
    asks,
    background,
    changes,
    commits,
    gpu,
    labs,
    memory,
    notebooks,
    problems,
    sources,
    sync,
    videos,
    workflows,
    workspaces,
)
from .backlog import Backlog, catching_up
from .baselines import Baselines, carry_over, head
from .comparison import compare, signatures
from .jobs import Job, Jobs
from .local_only import LocalOnly
from .watches import Snapshot, State, Watch, Watches, handout

_PACKAGE = Path(str(files("studioz")))

templates = Jinja2Templates(directory=_PACKAGE / "templates")
router = APIRouter()


@dataclass(frozen=True)
class Studio:
    main: Path
    """The repository's main checkout, which studioz never writes to."""
    settings: GlobalSettings
    watches: Watches
    statuses: problems.Statuses
    affected: changes.Affected
    baselines: Baselines
    pairs: changes.LangPairs
    backlog: Backlog
    """The workspaces' translation backlogs (`deckz i18n stale`)."""
    jobs: Jobs
    agents: agent.Agents
    login: "Login"
    drafter: Callable[[Path, list[str]], Awaitable[str]] = asks.draft_message
    """Writes a commit message (tests replace it)."""
    closing: Event = field(default_factory=Event)
    """Set when studioz stops: the pages' server-sent events end."""

    async def gone(self, request: Request) -> bool:
        """Whether a stream to `request`'s page should end.

        Returns:
            Whether the page went, or studioz stops.
        """
        return self.closing.is_set() or await request.is_disconnected()

    def workspace(self, name: str) -> workspaces.Workspace:
        found = workspaces.find(self.settings, name)
        if found is None:
            raise HTTPException(404, f"Pas d'espace de travail « {name} »")
        return found

    def deck(self, name: str, deck: str) -> tuple[workspaces.Workspace, Path]:
        found = self.workspace(name)
        directory = workspaces.deck_dir(found.worktree.path, deck)
        if directory is None:
            raise HTTPException(404, f"Pas de formation « {deck} » dans « {name} »")
        return found, directory

    def source(self, name: str, file: str) -> Path:
        found = self.workspace(name)
        paths = self.settings.paths
        scenes = paths.scenes_dir.relative_to(paths.git_dir)
        path = sources.source(found.worktree.path, file, scenes)
        if path is None:
            raise HTTPException(404, f"Pas de fichier modifiable « {file} »")
        return path


@dataclass
class Login:
    """Whether Claude Code is logged in as the person, checked now and then."""

    checked: float = -1e9
    ok: bool = False
    account: str = ""
    check: Callable[[], tuple[bool, str]] = agent.logged_in

    async def status(self) -> tuple[bool, str]:
        # `claude auth status` takes about a second: kept five minutes, less
        # while it says nobody is logged in.
        keep = 300 if self.ok else 10
        if monotonic() - self.checked > keep:
            self.ok, self.account = await asyncio.to_thread(self.check)
            self.checked = monotonic()
        return self.ok, self.account


class _Static(StaticFiles):
    """studioz's own files, checked again at each load (a 304 when unchanged).

    Without it, browsers keep them by a guess from their date: after a
    deckz update, a page could run yesterday's script against today's routes.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _studio(request: Request) -> Studio:
    return request.app.state.studio


StudioDep = Annotated[Studio, Depends(_studio)]


def _render(request: Request, name: str, **context: Any) -> Response:
    studio = _studio(request)
    return templates.TemplateResponse(
        request,
        name,
        {"repository": studio.main.name, "version": __version__, **context},
    )


def _ago(moment: datetime) -> str:
    seconds = (datetime.now(UTC) - moment).total_seconds()
    for unit, name in ((86400, "j"), (3600, "h"), (60, "min")):
        if seconds >= unit:
            return f"il y a {int(seconds // unit)} {name}"
    return "à l'instant"


def _size(size: int) -> str:
    for unit, name in ((1 << 30, "Go"), (1 << 20, "Mo"), (1 << 10, "ko")):
        if size >= unit:
            return f"{size / unit:.1f} {name}".replace(".", ",")
    return f"{size} o"


# The agent writes Markdown. Raw HTML in it stays text, and markdown-it
# refuses `javascript:` links.
_MARKDOWN = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable("table")


def _markdown(text: str) -> Markup:
    return Markup(_MARKDOWN.render(text))


def _dollars(amount: float) -> str:
    return f"{amount:.2f} $".replace(".", ",")


def _hours(hours: float) -> str:
    minutes = round(hours * 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


templates.env.filters["ago"] = _ago
templates.env.filters["dollars"] = _dollars
templates.env.filters["hours"] = _hours
templates.env.filters["gib"] = memory.gib
templates.env.filters["markdown"] = _markdown
templates.env.filters["workflow_text"] = workflows.text
templates.env.filters["deck_tree"] = workspaces.deck_tree


@router.get("/", response_class=HTMLResponse)
def home(request: Request, studio: StudioDep) -> Response:
    return _render(
        request,
        "home.html",
        workspaces=workspaces.workspaces(studio.settings),
        upstream=workspaces.upstream(studio.main),
        declared=workflows.declared_at(studio.main),
    )


@router.post("/espaces", response_class=HTMLResponse)
def create(
    request: Request, studio: StudioDep, name: Annotated[str, Form()]
) -> Response:
    try:
        created = workspaces.create(studio.settings, name.strip())
    except DeckzError as error:
        return _render(request, "_error.html", message=str(error))
    if not created.ready:
        return _render(request, "_setup.html", created=created)
    return Response(headers={"HX-Redirect": f"/espaces/{created.name}"})


@router.get("/espaces/{name}", response_class=HTMLResponse)
def workspace(request: Request, studio: StudioDep, name: str) -> Response:
    found = studio.workspace(name)
    workspaces.mark_used(found.worktree.path)
    return _render(
        request,
        "workspace.html",
        workspace=found,
        decks=workspaces.decks(found.worktree.path),
        declared=workflows.declared(found.worktree.path),
    )


@router.get("/espaces/{name}/formations/{deck:path}/pdf")
def pdf(studio: StudioDep, name: str, deck: str, lang: Lang = "fr") -> Response:
    _, directory = studio.deck(name, deck)
    path = handout(directory, lang)
    if not path.is_file():
        raise HTTPException(404, "Pas encore construit")
    return FileResponse(
        path, media_type="application/pdf", headers={"Cache-Control": "no-store"}
    )


@router.get("/espaces/{name}/formations/{deck:path}/cadres")
def deck_frames(studio: StudioDep, name: str, deck: str, lang: Lang = "fr") -> Response:
    """Each page of the deck's handout with its frame's source.

    Returns:
        `{"frames": [{page, title, file, line}...]}`, or no frames and the \
        reason, from what the last build recorded (`deckz show frames`).
    """
    _, directory = studio.deck(name, deck)
    try:
        found = frames(
            DeckSettings.from_yaml(directory), handout(directory, lang), query=False
        )
    except DeckzError as error:
        return JSONResponse({"frames": [], "error": str(error)})
    return JSONResponse({"frames": [asdict(frame) for frame in found]})


_POLL = 0.25
_HEARTBEAT = 15.0


def _event(name: str, data: object) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _state(snapshot: Snapshot, workspace: Path) -> dict[str, object]:
    # deckz names files by their absolute path.
    errors = [line.replace(f"{workspace}/", "") for line in snapshot.errors]
    return {"state": snapshot.state.value, "errors": errors}


async def watch_events(
    watch: Watch,
    pdf_url: str,
    disconnected: Callable[[], Awaitable[bool]],
    on_built: Callable[[], object] | None = None,
) -> AsyncIterator[str]:
    """`watch`'s state and new PDFs as server-sent events, until `disconnected`.

    Following them keeps the watch running. `on_built` is called, in a \
    thread, after each new PDF is announced.

    Yields:
        `state` events (building, built or failed, with the errors), and \
        `pdf` events with the URL of a new PDF.
    """
    watch.follow()
    try:
        last_state: dict[str, object] | None = None
        last_pdf = -1
        quiet = 0.0
        while not await disconnected():
            snapshot = watch.snapshot()
            if (state := _state(snapshot, watch.workspace)) != last_state:
                last_state = state
                quiet = 0.0
                yield _event("state", state)
            if snapshot.pdf_version and snapshot.pdf_version != last_pdf:
                last_pdf = snapshot.pdf_version
                quiet = 0.0
                yield _event("pdf", {"url": f"{pdf_url}&v={last_pdf}"})
                if on_built is not None and snapshot.state is State.BUILT:
                    await asyncio.to_thread(on_built)
            if quiet >= _HEARTBEAT:
                quiet = 0.0
                yield ": heartbeat\n\n"
            await asyncio.sleep(_POLL)
            quiet += _POLL
    finally:
        watch.unfollow()


@router.get("/espaces/{name}/formations/{deck:path}/evenements")
async def events(
    request: Request, studio: StudioDep, name: str, deck: str, lang: Lang = "fr"
) -> StreamingResponse:
    """The deck's live build.

    Returns:
        Its server-sent events (`watch_events`).
    """
    found, directory = studio.deck(name, deck)
    watch = await asyncio.to_thread(
        studio.watches.watch, found.worktree.path, directory, lang
    )
    pdf_url = f"/espaces/{quote(name)}/formations/{quote(deck)}/pdf?lang={lang}"
    return StreamingResponse(
        watch_events(
            watch,
            pdf_url,
            lambda: studio.gone(request),
            # A build of a workspace with no change is its last commit's.
            lambda: studio.baselines.capture(found.worktree.path, directory, lang),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/espaces/{name}/formations/{deck:path}/avant.pdf")
def baseline_pdf(
    studio: StudioDep, name: str, deck: str, lang: Lang = "fr"
) -> Response:
    """The deck's handout as of the workspace's last commit.

    Returns:
        The PDF.

    Raises:
        HTTPException: 404 until its baseline is there.
    """
    found, directory = studio.deck(name, deck)
    state = studio.baselines.get(found.worktree.path, directory, lang)
    if state.baseline is None or state.baseline.pdf is None:
        raise HTTPException(404, "Pas de version du dernier commit")
    return FileResponse(
        state.baseline.pdf,
        media_type="application/pdf",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/espaces/{name}/formations/{deck:path}/comparaison")
def comparison(
    request: Request, studio: StudioDep, name: str, deck: str, lang: Lang = "fr"
) -> Response:
    """The deck's frames changed since the workspace's last commit.

    Returns:
        The before/after view, which reloads itself while the baseline is \
        built, and on a `comparison-refresh` event.
    """
    found, directory = studio.deck(name, deck)
    path = found.worktree.path
    base = f"/espaces/{quote(name)}/formations/{quote(deck)}"
    context: dict[str, Any] = {
        "url": f"{base}/comparaison?lang={lang}",
        "retry_url": f"{base}/comparaison/reessayer?lang={lang}",
    }
    watch = studio.watches.get(path)
    snapshot = (
        watch.snapshot()
        if watch and watch.deck == directory and watch.lang == lang
        else None
    )
    if not background.changes(path):
        return _render(request, "_comparison.html", status="clean", **context)
    state = studio.baselines.get(path, directory, lang)
    context["state"] = state
    context["commit"] = background.git(
        path, "log", "-1", "--format=%h %s", state.commit
    )
    if state.baseline is None:
        return _render(request, "_comparison.html", status="baseline", **context)
    current = handout(directory, lang)
    if snapshot is None or not snapshot.built or not current.is_file():
        # The PDF there may be older than the files.
        return _render(request, "_comparison.html", status="waiting", **context)
    try:
        before = state.baseline.pdf
        result = compare(
            state.baseline.titles,
            signatures(before) if before else (),
            frames(DeckSettings.from_yaml(directory), current, query=False),
            signatures(current),
        )
    except (DeckzError, OSError, subprocess.CalledProcessError) as error:
        return _render(
            request, "_comparison.html", status="error", error=str(error), **context
        )
    return _render(
        request,
        "_comparison.html",
        status="compared",
        comparison=result,
        failed=snapshot.state is State.FAILED,
        before_url=f"{base}/avant.pdf?lang={lang}&c={state.commit}",
        after_url=f"{base}/pdf?lang={lang}&v={current.stat().st_mtime_ns}",
        **context,
    )


@router.post("/espaces/{name}/formations/{deck:path}/comparaison/reessayer")
def retry_baseline(
    request: Request, studio: StudioDep, name: str, deck: str, lang: Lang = "fr"
) -> Response:
    found, directory = studio.deck(name, deck)
    studio.baselines.retry(found.worktree.path, directory, lang)
    return comparison(request, studio, name, deck, lang)


@router.get("/espaces/{name}/formations/{deck:path}", response_class=HTMLResponse)
def deck_page(
    request: Request,
    studio: StudioDep,
    name: str,
    deck: str,
    lang: Lang = "fr",
    vue: str | None = None,
) -> Response:
    found, _ = studio.deck(name, deck)
    workspaces.mark_used(found.worktree.path)
    return _render(
        request,
        "deck.html",
        workspace=found,
        decks=workspaces.decks(found.worktree.path),
        deck=deck,
        lang=lang,
        view="changes" if vue == "modifications" else "slides",
        declared=workflows.declared(found.worktree.path),
    )


@router.get("/espaces/{name}/fichiers/{file:path}")
def read_source(studio: StudioDep, name: str, file: str) -> Response:
    """A file to edit.

    Returns:
        `{"text", "version"}`, the version to name when saving it.

    Raises:
        HTTPException: 415 if it isn't UTF-8 text.
    """
    try:
        text, version = sources.read(studio.source(name, file))
    except UnicodeDecodeError:
        raise HTTPException(415, f"« {file} » n'est pas du texte UTF-8") from None
    return JSONResponse({"text": text, "version": version})


@router.post("/espaces/{name}/fichiers/{file:path}")
def save_source(
    studio: StudioDep,
    name: str,
    file: str,
    version: Annotated[str, Form()],
    # An empty field counts as missing.
    text: Annotated[str, Form()] = "",
) -> Response:
    """Save a file, unless it changed on disk since its `version`.

    Returns:
        `{"version"}`, the new one; on a conflict, a 409 with the file's \
        version now.
    """
    try:
        saved = sources.save(studio.source(name, file), text, version)
    except sources.ChangedOnDiskError as error:
        return JSONResponse({"version": error.version}, status_code=409)
    return JSONResponse({"version": saved})


@router.get("/espaces/{name}/problemes", response_class=HTMLResponse)
def problems_panel(
    request: Request,
    studio: StudioDep,
    name: str,
    formation: str | None = None,
    lang: Lang = "fr",
) -> Response:
    """The workspace's Problems panel, and those of the deck on screen.

    Returns:
        The panel, which reloads itself while `deckz status` runs, and on \
        a `workspace-changed` event.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    report = studio.statuses.report(path)
    groups: list[problems.Group | None] = []
    if formation is not None:
        _, directory = studio.deck(name, formation)
        watch = studio.watches.get(path)
        if watch and watch.deck == directory and watch.lang == lang:
            groups.append(problems.build_problems(path, watch.snapshot()))
        groups.append(problems.shrunk(path, directory, lang))
        groups.append(problems.wrapped(path, directory, lang))
    groups += report.result or ()
    shown = [group for group in groups if group is not None]
    query = f"?formation={quote(formation)}&lang={lang}" if formation else ""
    return _render(
        request,
        "_problems.html",
        url=f"/espaces/{quote(name)}/problemes{query}",
        groups=shown,
        count=sum(len(group.problems) for group in shown),
        report=report,
        deck=formation,
        base=f"/espaces/{quote(name)}",
    )


@router.get("/espaces/{name}/modifications", response_class=HTMLResponse)
def changes_panel(
    request: Request,
    studio: StudioDep,
    name: str,
    formation: str | None = None,
    lang: Lang = "fr",
) -> Response:
    """The workspace's Changes panel.

    Returns:
        The panel, which reloads itself, more often while the decks the \
        changes reach are being found.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    groups = changes.grouped(path, workspaces.decks(path), studio.pairs.get(path))
    query = f"?formation={quote(formation)}&lang={lang}" if formation else ""
    return _render(
        request,
        "_changes.html",
        workspace=found,
        url=f"/espaces/{quote(name)}/modifications{query}",
        groups=groups,
        count=sum(len(group.files) for group in groups),
        affected=studio.affected.report(path),
        deck=formation,
        lang=lang,
        notebook_page=partial(
            problems.notebook,
            labs_dir=studio.settings.paths.labs_notebooks_dir.relative_to(
                studio.settings.paths.git_dir
            ),
        ),
    )


@dataclass(frozen=True)
class Draft:
    """The commit dialog's fields, as posted."""

    listed: frozenset[str]
    """The files the dialog showed: one changed since is chosen by default."""
    paths: frozenset[str]
    """The files chosen."""
    message: str
    lang_sync: str
    """How to answer the `Lang-sync` rule (`commits.LANG_SYNC_CHOICES`)."""
    reason: str
    deck: str | None
    """The deck on screen, whose live build may become the new baseline."""
    lang: Lang

    def selected(self, found: list[background.Change], *, shown: bool) -> set[str]:
        """The files chosen among those changed.

        Args:
            found: The files changed now.
            shown: Whether the selection is shown before it's used: a file \
                the dialog didn't list yet is then chosen by default; never \
                in a commit, which holds only what the person saw.

        Returns:
            Their paths.
        """
        return {
            change.path
            for change in found
            if change.path in self.paths or (shown and change.path not in self.listed)
        }

    @property
    def opening(self) -> bool:
        """Whether the dialog is being opened: none of its fields posted."""
        return not (self.listed or self.paths or self.message)

    def kept(self) -> dict[str, object]:
        return {
            "listed": sorted(self.listed),
            "paths": sorted(self.paths),
            "message": self.message,
            "lang_sync": self.lang_sync,
            "reason": self.reason,
        }

    def resumed(self, workspace: Path) -> "Draft":
        """This one, or, opening the dialog, the workspace's kept draft.

        Returns:
            The draft to show: the deck and language this one's.
        """
        found = commits.kept_draft(workspace) if self.opening else None
        if not found:
            return self

        def files(key: str) -> frozenset[str]:
            value = found.get(key)
            return (
                frozenset(map(str, value)) if isinstance(value, list) else frozenset()
            )

        return replace(
            self,
            listed=files("listed"),
            paths=files("paths"),
            message=str(found.get("message") or ""),
            lang_sync=str(found.get("lang_sync") or ""),
            reason=str(found.get("reason") or ""),
        )


def _draft(
    listed: Annotated[list[str] | None, Form()] = None,
    path: Annotated[list[str] | None, Form()] = None,
    message: Annotated[str, Form()] = "",
    lang_sync: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
    formation: Annotated[str, Form()] = "",
    lang: Annotated[Lang, Form()] = "fr",
) -> Draft:
    return Draft(
        frozenset(listed or ()),
        frozenset(path or ()),
        message,
        lang_sync,
        reason,
        formation or None,
        lang,
    )


DraftDep = Annotated[Draft, Depends(_draft)]


def _commit_dialog(
    request: Request,
    studio: Studio,
    found: workspaces.Workspace,
    draft: Draft,
    **context: Any,
) -> Response:
    path = found.worktree.path
    changed = background.changes(path)
    pairs = studio.pairs.get(path)
    selected = draft.selected(changed, shown=True)
    alone = one_sided(set(commits.to_stage(changed, selected)), pairs)
    ported = catching_up(
        [str(c.changed_path) for c in alone], studio.backlog.report(path).result or ()
    )
    if ported and not draft.lang_sync and not draft.reason:
        # Porting the backlog changes one side only, with nothing to bring back.
        reason = "portage de " + ", ".join(stale.path for stale in ported)
        draft = replace(draft, lang_sync="only", reason=reason)
    report = studio.statuses.report(path)
    return _render(
        request,
        "_commit.html",
        workspace=found,
        draft=draft,
        groups=changes.grouped(path, workspaces.decks(path), pairs),
        selected=selected,
        one_sided=alone,
        sides={change.changed for change in alone},
        report=report,
        checks=next((g for g in report.result or () if g.key == "checks"), None),
        blocked=commits.blocked(path, changed),
        **context,
    )


@router.post("/espaces/{name}/commit/formulaire", response_class=HTMLResponse)
def commit_form(
    request: Request, studio: StudioDep, name: str, draft: DraftDep
) -> Response:
    """The commit dialog, with the fields posted kept, else the draft kept.

    Returns:
        Its content, the files changed now listed.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    if not draft.opening:
        commits.keep_draft(path, draft.kept())
    return _commit_dialog(request, studio, found, draft.resumed(path))


@router.post("/espaces/{name}/commit/brouillon", status_code=204)
def commit_keep_draft(studio: StudioDep, name: str, draft: DraftDep) -> None:
    """Keep the dialog's fields as the person writes them."""
    if not draft.opening:
        commits.keep_draft(studio.workspace(name).worktree.path, draft.kept())


@router.post("/espaces/{name}/commit/proposer", response_class=HTMLResponse)
async def commit_draft(
    request: Request, studio: StudioDep, name: str, draft: DraftDep
) -> Response:
    """A commit message for the files ticked, by Claude (`asks.draft_message`).

    Returns:
        The dialog's message box, with the message proposed, or the one \
        written and why there's none.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    changed = await asyncio.to_thread(background.changes, path)
    paths = commits.to_stage(changed, draft.selected(changed, shown=False))
    message, error = draft.message, None
    ok, why = await studio.login.status()
    if not ok:
        error = why
    elif not paths:
        error = "Cochez d'abord les fichiers du commit."
    else:
        try:
            message = await studio.drafter(path, paths) or message
        except Exception as failure:
            # Whatever Claude Code says (a limit, no network): the person writes it.
            error = f"Pas de proposition : {str(failure)[:200]}"
        else:
            commits.keep_draft(path, replace(draft, message=message).kept())
    return _render(
        request,
        "_commit_message.html",
        workspace=found,
        message=message,
        draft_error=error,
    )


@router.post("/espaces/{name}/commit", response_class=HTMLResponse)
def commit(request: Request, studio: StudioDep, name: str, draft: DraftDep) -> Response:
    """Commit the files chosen, unless something's missing or a hook refuses.

    Returns:
        The commit dialog, with the new commit and what's left, or with \
        why it wasn't made.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    changed = background.changes(path)
    selected = draft.selected(changed, shown=False)
    paths = commits.to_stage(changed, selected)
    error = commits.blocked(path, changed)
    if error is None and not selected:
        error = "Cochez au moins un fichier."
    if error is None and not draft.message.strip():
        error = "Écrivez le message du commit."
    trailer = None
    alone = one_sided(set(paths), studio.pairs.get(path))
    if error is None and alone and lang_sync_kind(draft.message) is None:
        try:
            trailer = commits.lang_sync_trailer(alone, draft.lang_sync, draft.reason)
        except ValueError as refusal:
            error = str(refusal)
    if error is not None:
        return _commit_dialog(request, studio, found, draft, error=error)
    result = commits.commit(path, paths, draft.message, trailer)
    if isinstance(result, commits.Refused):
        return _commit_dialog(request, studio, found, draft, refused=result.output)
    _keep_baseline(studio, path, draft)
    # What the person left out stays out; the message starts over.
    fresh = Draft(draft.listed, draft.paths, "", "", "", draft.deck, draft.lang)
    commits.keep_draft(path, fresh.kept())
    response = _commit_dialog(request, studio, found, fresh, committed=result)
    response.headers["HX-Trigger"] = "workspace-changed, comparison-refresh"
    return response


def _keep_baseline(studio: Studio, workspace: Path, draft: Draft) -> None:
    """Keep the deck on screen's live build as the new commit's baseline.

    It is the commit's when the commit left no change behind, and the build
    is done (`Baselines.capture` checks the former).
    """
    directory = workspaces.deck_dir(workspace, draft.deck) if draft.deck else None
    watch = studio.watches.get(workspace)
    if (
        directory is not None
        and watch is not None
        and (watch.deck, watch.lang) == (directory, draft.lang)
        and watch.snapshot().state is State.BUILT
    ):
        studio.baselines.capture(workspace, directory, draft.lang)


@router.get("/espaces/{name}/synchronisation", response_class=HTMLResponse)
def sync_panel(
    request: Request, studio: StudioDep, name: str, formation: str = ""
) -> Response:
    """Where the workspace stands against the upstream branch, without fetching.

    Returns:
        The navigator's Synchronisation panel.
    """
    found = studio.workspace(name)
    up = sync.upstream(studio.main)
    state = sync.state(found.worktree.path, up) if up else None
    return _render(
        request, "_sync_panel.html", workspace=found, state=state, deck=formation
    )


Formation = Annotated[str, Form()]
"""The deck on screen, whose page opens a file in its editor; empty elsewhere."""


def _sync_dialog(
    request: Request,
    studio: Studio,
    name: str,
    action: Callable[[Path, sync.Upstream], sync.Outcome | None],
    deck: str,
    *,
    moved: bool = False,
) -> Response:
    """The Synchronisation dialog, after `action`.

    Args:
        request: The request.
        studio: studioz.
        name: The workspace.
        action: What to do in it, given the upstream branch: its outcome, \
            or None to only show where it stands.
        deck: The deck on screen, if any: its page opens a conflict's file.
        moved: Whether `action` may have moved the workspace's HEAD, which \
            the other panels and the before/after view follow.

    Returns:
        The dialog's content.

    Raises:
        HTTPException: 409 without an upstream branch.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    up = sync.upstream(studio.main)
    if up is None:
        raise HTTPException(409, "Pas de branche amont avec laquelle synchroniser")
    outcome = action(path, up)
    state = sync.state(path, up)
    response = _render(
        request,
        "_sync.html",
        workspace=found,
        state=state,
        outcome=outcome,
        deck=deck,
        editable={
            file
            for file in state.conflicts or ()
            if deck and sources.source(path, file) is not None
        },
    )
    if outcome is not None:
        events = ["workspace-changed"] + (["comparison-refresh"] if moved else [])
        response.headers["HX-Trigger"] = ", ".join(events)
    return response


@router.post("/espaces/{name}/synchronisation/formulaire", response_class=HTMLResponse)
def sync_form(
    request: Request, studio: StudioDep, name: str, formation: Formation = ""
) -> Response:
    return _sync_dialog(request, studio, name, lambda *_: None, formation)


@router.post(
    "/espaces/{name}/synchronisation/mettre-a-jour", response_class=HTMLResponse
)
def sync_update(
    request: Request, studio: StudioDep, name: str, formation: Formation = ""
) -> Response:
    """Fetch, and rebase the workspace's commits onto the upstream branch.

    Returns:
        The dialog, with how it went (a conflict to fix, typically).
    """
    return _sync_dialog(request, studio, name, sync.update, formation, moved=True)


@router.post("/espaces/{name}/synchronisation/verifier", response_class=HTMLResponse)
def sync_check(
    request: Request, studio: StudioDep, name: str, formation: Formation = ""
) -> Response:
    """Update the workspace, then check its commits as they would be pushed.

    Returns:
        The dialog, offering to publish the commit checked if it passes.
    """
    return _sync_dialog(request, studio, name, sync.prepare, formation, moved=True)


@router.post("/espaces/{name}/synchronisation/publier", response_class=HTMLResponse)
def sync_publish(
    request: Request,
    studio: StudioDep,
    name: str,
    sha: Annotated[str, Form()],
    formation: Formation = "",
) -> Response:
    """Push the commit checked, unless the workspace moved since.

    Returns:
        The dialog, with how it went.
    """
    return _sync_dialog(
        request, studio, name, lambda path, up: sync.publish(path, up, sha), formation
    )


@router.post("/espaces/{name}/synchronisation/continuer", response_class=HTMLResponse)
def sync_continue(
    request: Request, studio: StudioDep, name: str, formation: Formation = ""
) -> Response:
    return _sync_dialog(
        request,
        studio,
        name,
        lambda path, _: sync.continue_rebase(path),
        formation,
        moved=True,
    )


@router.post("/espaces/{name}/synchronisation/abandonner", response_class=HTMLResponse)
def sync_abort(
    request: Request, studio: StudioDep, name: str, formation: Formation = ""
) -> Response:
    return _sync_dialog(
        request, studio, name, lambda path, _: sync.abort(path), formation, moved=True
    )


@router.get("/espaces/{name}/taches/resume", response_class=HTMLResponse)
def jobs_badge(request: Request, studio: StudioDep, name: str) -> Response:
    """The status bar's summary of the workspace's jobs.

    Returns:
        How many run or wait, else how the last one ended; with the last \
        ones ended, which the page notifies once each (`notifications.js`).
    """
    found = studio.workspace(name)
    jobs = studio.jobs.jobs(found.worktree.path)
    ended = [
        {
            "id": job.id,
            "ended": job.ended.timestamp() * 1000,
            "state": job.state.name.lower(),
            "title": job.title,
            "detail": job.failure,
            "link": job.link,
        }
        for job in jobs
        if job.finished and job.ended
    ][:10]
    return _render(
        request,
        "_jobs_badge.html",
        workspace=found,
        active=[job for job in jobs if not job.finished],
        last=next((job for job in jobs if job.finished), None),
        ended=ended,
    )


@router.get("/espaces/{name}/taches", response_class=HTMLResponse)
def jobs_list(request: Request, studio: StudioDep, name: str) -> Response:
    """The workspace's jobs, the latest one's log shown.

    Returns:
        The panel's Tâches tab, which reloads itself when a job starts.
    """
    found = studio.workspace(name)
    return _render(
        request,
        "_jobs.html",
        workspace=found,
        jobs=studio.jobs.jobs(found.worktree.path),
    )


def _job_or_404(
    studio: Studio, name: str, job_id: int
) -> tuple[workspaces.Workspace, Job]:
    found = studio.workspace(name)
    job = studio.jobs.get(found.worktree.path, job_id)
    if job is None:
        raise HTTPException(404, f"Pas de tâche {job_id} dans « {name} »")
    return found, job


@router.get("/espaces/{name}/taches/{job_id}", response_class=HTMLResponse)
def job_view(request: Request, studio: StudioDep, name: str, job_id: int) -> Response:
    """A job and its log, which reloads itself until the job ends.

    Returns:
        The job's section; once it ended, with the event reloading the \
        Tâches tab, whose count of the jobs running it changed.
    """
    found, job = _job_or_404(studio, name, job_id)
    response = _render(request, "_job.html", workspace=found, job=job, open=True)
    if job.finished:
        response.headers["HX-Trigger-After-Settle"] = "jobs-changed"
    return response


@router.post("/espaces/{name}/taches/{job_id}/arreter", response_class=HTMLResponse)
def job_stop(request: Request, studio: StudioDep, name: str, job_id: int) -> Response:
    found, job = _job_or_404(studio, name, job_id)
    studio.jobs.stop(found.worktree.path, job_id)
    return _render(request, "_job.html", workspace=found, job=job, open=True)


@router.post("/espaces/{name}/taches/{job_id}/forcer", response_class=HTMLResponse)
def job_force(request: Request, studio: StudioDep, name: str, job_id: int) -> Response:
    """Start a job held for memory anyway.

    Returns:
        The job's section.
    """
    found, job = _job_or_404(studio, name, job_id)
    studio.jobs.force(found.worktree.path, job_id)
    return _render(request, "_job.html", workspace=found, job=job, open=True)


@router.get("/memoire", response_class=HTMLResponse)
def memory_badge(request: Request, studio: StudioDep) -> Response:
    """The status bar's memory item: what's available, short or not.

    Returns:
        The item, nothing where the memory can't be read.
    """
    return _render(
        request,
        "_memory_badge.html",
        found=studio.jobs.memory(),
        min_free=studio.jobs.min_free,
    )


@router.post("/espaces/{name}/taches/{job_id}/relancer", response_class=HTMLResponse)
def job_rerun(request: Request, studio: StudioDep, name: str, job_id: int) -> Response:
    """Run a finished build again, as it ran.

    Returns:
        The Tâches tab, the new job first.

    Raises:
        HTTPException: 409 for a job that must be started from its dialog.
    """
    found, _ = _job_or_404(studio, name, job_id)
    if studio.jobs.rerun(found.worktree.path, job_id) is None:
        raise HTTPException(409, "Cette tâche se relance depuis sa fenêtre")
    response = jobs_list(request, studio, name)
    response.headers["HX-Trigger-After-Settle"] = "jobs-changed"
    return response


def _started(request: Request, found: workspaces.Workspace) -> Response:
    """The job just started, its log shown, in the dialog that started it.

    Returns:
        The response, whose events (once in the page) close the dialog for \
        the panel's Tâches tab and reload what shows the jobs.
    """
    job = _studio(request).jobs.jobs(found.worktree.path)[0]
    response = _render(request, "_job_started.html", workspace=found, job=job)
    response.headers["HX-Trigger-After-Settle"] = json.dumps(
        {"jobs-changed": None, "job-started": None}
    )
    return response


@router.post(
    "/espaces/{name}/formations/{deck:path}/construire/formulaire",
    response_class=HTMLResponse,
)
def build_form(request: Request, studio: StudioDep, name: str, deck: str) -> Response:
    """What a full build of the deck produces, each output to choose.

    Returns:
        The build dialog's content.
    """
    found, _ = studio.deck(name, deck)
    return _render(
        request,
        "_build.html",
        workspace=found,
        deck=deck,
        kinds=actions.KINDS,
        chosen=actions.DEFAULT_KINDS,
        langs=("fr", "en"),
    )


@router.post("/espaces/{name}/construire/formulaire", response_class=HTMLResponse)
def build_all_form(request: Request, studio: StudioDep, name: str) -> Response:
    """What a build of every deck produces, each output to choose.

    Returns:
        The build dialog's content, for every deck.
    """
    return _render(
        request,
        "_build.html",
        workspace=studio.workspace(name),
        deck="",
        kinds=actions.KINDS,
        chosen=actions.DEFAULT_KINDS,
        langs=("fr",),
    )


@router.post("/espaces/{name}/construire", response_class=HTMLResponse)
def build_all(
    request: Request,
    studio: StudioDep,
    name: str,
    kind: Annotated[list[str] | None, Form()] = None,
    lang: Annotated[list[Lang] | None, Form()] = None,
) -> Response:
    """Start a job building every deck's outputs chosen (`deckz run decks`).

    Returns:
        The job, or the form again with what's missing.
    """
    found = studio.workspace(name)
    kinds = frozenset(k for k in kind or () if k in actions.KINDS)
    langs = [code for code in LANGS if code in (lang or ())]
    if not langs or not kinds & {"handout", "presentation", "print", "html"}:
        return _render(
            request,
            "_build.html",
            workspace=found,
            deck="",
            kinds=actions.KINDS,
            chosen=kinds,
            langs=langs,
            error="Choisissez au moins une langue et un document à produire.",
        )
    path = found.worktree.path
    studio.jobs.submit(
        path,
        actions.build_title("toutes les formations", kinds, langs),
        actions.build_steps(path, kinds, langs, every_deck=True),
        rerun=True,
    )
    return _started(request, found)


@router.post(
    "/espaces/{name}/formations/{deck:path}/construire", response_class=HTMLResponse
)
def build_deck(
    request: Request,
    studio: StudioDep,
    name: str,
    deck: str,
    kind: Annotated[list[str] | None, Form()] = None,
    lang: Annotated[list[Lang] | None, Form()] = None,
) -> Response:
    """Start a job building the deck's outputs chosen, in the languages chosen.

    Returns:
        The job, or the form again with what's missing.
    """
    found, directory = studio.deck(name, deck)
    kinds = frozenset(k for k in kind or () if k in actions.KINDS)
    langs = [code for code in LANGS if code in (lang or ())]
    if not langs or not kinds & {"handout", "presentation", "print", "html"}:
        return _render(
            request,
            "_build.html",
            workspace=found,
            deck=deck,
            kinds=actions.KINDS,
            chosen=kinds,
            langs=langs,
            error="Choisissez au moins une langue et un document à produire.",
        )
    path = found.worktree.path
    studio.jobs.submit(
        path,
        actions.build_title(deck, kinds, langs),
        actions.build_steps(path, kinds, langs),
        directory,
        rerun=True,
    )
    return _started(request, found)


@router.post(
    "/espaces/{name}/formations/{deck:path}/envoyer/formulaire",
    response_class=HTMLResponse,
)
def upload_form(request: Request, studio: StudioDep, name: str, deck: str) -> Response:
    """The deck's PDFs an upload would send, the outdated ones marked.

    Returns:
        The upload dialog's content.
    """
    found, directory = studio.deck(name, deck)
    plan = actions.upload_plan(found.worktree.path, directory)
    return _render(request, "_upload.html", workspace=found, deck=deck, plan=plan)


@router.post(
    "/espaces/{name}/formations/{deck:path}/envoyer", response_class=HTMLResponse
)
def upload_deck(
    request: Request,
    studio: StudioDep,
    name: str,
    deck: str,
    skip_checks: Annotated[bool, Form()] = False,
) -> Response:
    """Start a job uploading the deck's PDFs (deckz refuses outdated ones).

    Returns:
        The job.
    """
    found, directory = studio.deck(name, deck)
    path = found.worktree.path
    studio.jobs.submit(
        path,
        f"Envoyer les PDF de {deck} sur Google Drive",
        actions.upload_steps(path, skip_checks=skip_checks),
        directory,
        form=f"/espaces/{name}/formations/{deck}/envoyer/formulaire",
        needs_memory=False,
    )
    return _started(request, found)


def _publication(studio: Studio, name: str) -> dict[str, Any]:
    """What the publish dialog and the Publication panel show.

    Returns:
        Their templates' context.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    report = studio.statuses.report(path)
    groups = {group.key: group for group in report.result or ()}
    up = sync.upstream(studio.main)
    return {
        "workspace": found,
        "report": report,
        "pending": {what: groups.get(what) for what in actions.PUBLISHABLE},
        "publishable": actions.PUBLISHABLE,
        "ahead": len(sync.state(path, up).ahead) if up else 0,
        "upstream": up,
    }


@router.post("/espaces/{name}/publier/formulaire", response_class=HTMLResponse)
def publish_form(request: Request, studio: StudioDep, name: str) -> Response:
    """What's not published, and what publishing does.

    Returns:
        The publish dialog's content.
    """
    return _render(request, "_publish.html", **_publication(studio, name))


@router.get("/espaces/{name}/publication", response_class=HTMLResponse)
def publication_panel(request: Request, studio: StudioDep, name: str) -> Response:
    """The sidebar's Publication panel: what the labs and videos wait for.

    Returns:
        The panel, which reloads itself while `deckz status` runs, and on \
        a `workspace-changed` event; its buttons open the publish dialog.
    """
    return _render(request, "_publication.html", **_publication(studio, name))


@router.post("/espaces/{name}/publier", response_class=HTMLResponse)
def publish(
    request: Request, studio: StudioDep, name: str, what: Annotated[str, Form()]
) -> Response:
    """Start a job publishing the workspace's labs or videos.

    Returns:
        The job.

    Raises:
        HTTPException: 422 for something not publishable.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    try:
        steps = actions.publish_steps(path, what)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    studio.jobs.submit(
        path,
        f"Publier {actions.PUBLISHABLE[what][0]}",
        steps,
        form=f"/espaces/{name}/publier/formulaire",
        needs_memory=False,
    )
    return _started(request, found)


def _videos(studio: Studio, name: str) -> tuple[workspaces.Workspace, videos.Listing]:
    """The workspace's videos, the renders of its last commit kept on the way.

    Returns:
        The workspace and its videos.
    """
    found = studio.workspace(name)
    listed = videos.listing(found.worktree.path)
    videos.keep_baselines(found.worktree.path, listed)
    return found, listed


@router.get("/espaces/{name}/videos", response_class=HTMLResponse)
def videos_panel(
    request: Request, studio: StudioDep, name: str, video: str = ""
) -> Response:
    """The sidebar's Vidéos view: each scene and where its renders stand.

    Returns:
        The view's list, which reloads when the workspace changes or a job \
        starts or ends.
    """
    found, listed = _videos(studio, name)
    return _render(
        request,
        "_videos.html",
        workspace=found,
        listing=listed,
        current=video,
        states=videos.STATES,
    )


def _video(
    studio: Studio, name: str, video: str
) -> tuple[workspaces.Workspace, videos.Listing, videos.Video]:
    found, listed = _videos(studio, name)
    scene = listed.find(video)
    if scene is None:
        detail = listed.error or f"Pas de vidéo « {video} » dans « {name} »"
        raise HTTPException(404, detail)
    return found, listed, scene


@router.get("/espaces/{name}/rendus/{file:path}")
def video_file(studio: StudioDep, name: str, file: str) -> Response:
    """A render or its poster, or a render as of the last commit.

    Returns:
        The file.

    Raises:
        HTTPException: 404 for anything else.
    """
    found = studio.workspace(name)
    paths = studio.settings.paths
    path = videos.served(
        found.worktree.path, file, paths.videos_dir.relative_to(paths.git_dir)
    )
    if path is None:
        raise HTTPException(404, f"Pas de rendu « {file} »")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.get("/espaces/{name}/videos/{video:path}/lecteur", response_class=HTMLResponse)
def video_player(
    request: Request,
    studio: StudioDep,
    name: str,
    video: str,
    lang: Lang = "fr",
    vue: str | None = None,
) -> Response:
    """The scene's render, or its render as of the last commit beside it.

    Returns:
        The player, with the scene's state and its render buttons, which \
        reloads when the workspace changes or a job starts or ends.
    """
    found, listed, scene = _video(studio, name, video)
    path = found.worktree.path
    render = scene.render(lang)
    rendered = path / render.file
    before = videos.baseline(path, scene, render)
    return _render(
        request,
        "_video_player.html",
        workspace=found,
        scene=scene,
        render=render,
        lang=lang,
        view="changes" if vue == "avant-apres" else "render",
        states=videos.STATES,
        published_quality=listed.published_quality,
        draft_quality=videos.DRAFT_QUALITY,
        rendered=rendered.is_file(),
        version=rendered.stat().st_mtime_ns if rendered.is_file() else 0,
        before=before.relative_to(path).as_posix() if before else None,
        before_version=before.stat().st_mtime_ns if before else 0,
        unchanged=videos.unchanged(path, scene),
    )


@router.post("/espaces/{name}/videos/{video:path}/rendre", response_class=HTMLResponse)
def render_video(
    studio: StudioDep, name: str, video: str, final: Annotated[bool, Form()] = False
) -> Response:
    """Start a job rendering the scene, a draft or at the published quality.

    Returns:
        No content, with the events opening the panel's Tâches tab.
    """
    found, listed, scene = _video(studio, name, video)
    path = found.worktree.path
    quality = listed.published_quality if final else videos.DRAFT_QUALITY
    title = (
        f"Rendu final de la vidéo {scene.video} ({quality})"
        if final
        else f"Brouillon de la vidéo {scene.video} ({quality})"
    )
    studio.jobs.submit(
        path, title, videos.render_steps(path, scene.video, quality), rerun=True
    )
    return Response(
        headers={
            "HX-Trigger-After-Settle": json.dumps(
                {"jobs-changed": None, "job-started": None}
            ),
            "HX-Reswap": "none",
        }
    )


@router.get("/espaces/{name}/videos/{video:path}", response_class=HTMLResponse)
def video_page(
    request: Request,
    studio: StudioDep,
    name: str,
    video: str,
    lang: Lang = "fr",
    vue: str | None = None,
) -> Response:
    """A scene's page: its render, and its module in the editor beside it.

    Returns:
        The page; the player (`video_player`) loads itself, deckz's listing \
        taking under a second.
    """
    found = studio.workspace(name)
    workspaces.mark_used(found.worktree.path)
    return _render(
        request,
        "video.html",
        workspace=found,
        decks=workspaces.decks(found.worktree.path),
        video=video,
        lang=lang,
        view="changes" if vue == "avant-apres" else "render",
        declared=workflows.declared(found.worktree.path),
    )


@router.get("/espaces/{name}/tp", response_class=HTMLResponse)
def labs_panel(
    request: Request, studio: StudioDep, name: str, tp: str = ""
) -> Response:
    """The sidebar's TP view: each lab, its notebooks by kind and language.

    Returns:
        The view's list, which reloads when the workspace changes.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    return _render(
        request,
        "_labs.html",
        workspace=found,
        listing=labs.listing(path),
        changed={change.path for change in background.changes(path)},
        current=tp,
        kinds=labs.KINDS,
    )


def _notebook(
    studio: Studio, name: str, notebook: str, lang: Lang
) -> tuple[workspaces.Workspace, labs.Listing, labs.Notebook]:
    found = studio.workspace(name)
    listed = labs.listing(found.worktree.path)
    shown = listed.find(notebook, lang)
    if shown is None:
        detail = listed.error or f"Pas de notebook « {notebook} » dans « {name} »"
        raise HTTPException(404, detail)
    return found, listed, shown


@router.get("/espaces/{name}/tp/{notebook:path}/apercu", response_class=HTMLResponse)
def lab_view(
    request: Request,
    studio: StudioDep,
    name: str,
    notebook: str,
    lang: Lang = "fr",
    vue: str | None = None,
) -> Response:
    """The notebook rendered, or its changes since the last commit.

    Returns:
        The frame showing it (`lab_frame`), kept as it is while the \
        notebook doesn't change, which reloads when the workspace changes.
    """
    found, listed, shown = _notebook(studio, name, notebook, lang)
    path = found.worktree.path
    file = path / shown.file
    stat = file.stat()
    view = "changes" if vue == "avant-apres" else "render"
    change = next((c for c in background.changes(path) if c.path == shown.file), None)
    version = f"{stat.st_mtime_ns}-{stat.st_size}"
    if view == "changes":
        version += f"-{labs.head(path)[:12]}"
    return _render(
        request,
        "_lab_view.html",
        workspace=found,
        notebook=shown,
        lang=lang,
        languages=listed.languages(shown.name),
        view=view,
        version=version,
        changed=change is not None,
        new=change is not None and change.status in {"??", "A ", "AM"},
        kinds=labs.KINDS,
    )


@router.get("/espaces/{name}/tp/{notebook:path}/rendu", response_class=HTMLResponse)
def lab_frame(
    request: Request,
    studio: StudioDep,
    name: str,
    notebook: str,
    lang: Lang = "fr",
    vue: str | None = None,
) -> Response:
    """The page inside the frame: the notebook, or its changes.

    Served sandboxed (`notebooks.frame_headers`): its outputs' HTML is the
    notebook's.

    Returns:
        The page.

    Raises:
        HTTPException: 404 for a notebook that isn't JSON.
    """
    found, _, shown = _notebook(studio, name, notebook, lang)
    path = found.worktree.path
    current = labs.read(path, shown.file)
    if current is None:
        raise HTTPException(404, f"« {shown.file} » n'est pas un notebook lisible")
    context: dict[str, Any] = {"notebook": shown, "lang": shown.language}
    if vue == "avant-apres":
        before = labs.committed(path, shown.file)
        context["changes"] = notebooks.compare(before or {"cells": []}, current)
        context["new"] = before is None
    else:
        context["cells"] = notebooks.cells(current)
    origin = f"{request.url.scheme}://{request.url.netloc}"
    return templates.TemplateResponse(
        request, "notebook.html", context, headers=notebooks.frame_headers(origin)
    )


@router.post("/espaces/{name}/tp/{notebook:path}/ouvrir", response_class=HTMLResponse)
def open_lab(studio: StudioDep, name: str, notebook: str, lang: Lang = "fr") -> str:
    """Open the notebook in the application the system opens notebooks with.

    Returns:
        What happened, for the page's notice.
    """
    found, _, shown = _notebook(studio, name, notebook, lang)
    error = labs.open_in_editor(found.worktree.path / shown.file)
    if error:
        return f"Le notebook n'a pas pu être ouvert : {error}"
    return f"{shown.file} ouvert dans l'application des notebooks."


@router.get("/espaces/{name}/tp/{notebook:path}", response_class=HTMLResponse)
def lab_page(
    request: Request,
    studio: StudioDep,
    name: str,
    notebook: str,
    lang: Lang = "fr",
    vue: str | None = None,
) -> Response:
    """A notebook's page: rendered as Colab shows it, or its changes.

    Returns:
        The page; the notebook (`lab_view`) loads itself.
    """
    found = studio.workspace(name)
    workspaces.mark_used(found.worktree.path)
    return _render(
        request,
        "lab.html",
        workspace=found,
        decks=workspaces.decks(found.worktree.path),
        notebook=notebook,
        lang=lang,
        view="changes" if vue == "avant-apres" else "render",
        kinds=labs.KINDS,
        declared=workflows.declared(found.worktree.path),
    )


Files = Annotated[list[str] | None, Form()]


@dataclass(frozen=True)
class _PassChoice:
    """What the GPU modal asks, as the person left it."""

    candidates: tuple[labs.Notebook, ...]
    """The notebooks it was opened with, each to tick."""
    notebooks: tuple[labs.Notebook, ...]
    """Those ticked."""
    short: bool
    write_outputs: bool
    outputs_possible: bool
    """A full run of demos only: deckz refuses outputs otherwise."""
    ceiling: float | None
    """The person's, None for the one offered."""


def _pass_choice(
    listing: labs.Listing,
    candidates: list[str] | None,
    carnet: list[str] | None,
    mode: str,
    sorties: str | None,
    sorties_vu: str | None,
    plafond: float | None,
    plafond_auto: float | None,
) -> _PassChoice:
    """The modal's choices, from its fields: unknown notebooks left out.

    Returns:
        Them, outputs on by default for a full run of demos.
    """
    by_file = {notebook.file: notebook for notebook in listing.notebooks}
    offered = [by_file[file] for file in candidates or () if file in by_file]
    chosen = [by_file[file] for file in carnet or () if file in by_file]
    if candidates is None:
        offered = chosen
    else:
        chosen = [notebook for notebook in offered if notebook in chosen]
    short = mode == "court"
    possible = bool(chosen) and not short and all(n.kind == "demo" for n in chosen)
    # Outputs default to on when possible: what a full run of demos is for.
    write_outputs = possible and (sorties is not None or sorties_vu is None)
    ceiling = plafond if plafond and plafond > 0 and plafond != plafond_auto else None
    return _PassChoice(
        tuple(offered), tuple(chosen), short, write_outputs, possible, ceiling
    )


@router.post("/espaces/{name}/gpu/formulaire", response_class=HTMLResponse)
def gpu_form(
    request: Request,
    studio: StudioDep,
    name: str,
    tp: Files = None,
    candidat: Files = None,
    carnet: Files = None,
    rouvrir: Annotated[list[str] | None, Query(alias="carnet")] = None,
    mode: Annotated[str, Form()] = "complet",
    sorties: Annotated[str | None, Form()] = None,
    sorties_vu: Annotated[str | None, Form()] = None,
    plafond: Annotated[float | None, Form()] = None,
    plafond_auto: Annotated[float | None, Form()] = None,
) -> Response:
    """The modal confirming a GPU pass: the offer, the estimate, the ceiling.

    Opened with lab notebooks' names (`tp`: every language of each), or
    their files (`carnet` in the URL, when a pass is started again); then
    sent again as the person changes it (`candidat`, the notebooks offered;
    `carnet`, those ticked), deckz's dry run each time.

    Returns:
        The modal's content, its button naming the GPU and the cost.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    listing = labs.listing(path)
    if candidat is None:  # Opened: every notebook named, ticked.
        candidat = [*(rouvrir or ())]
        for name in tp or ():
            candidat += [n.file for n in listing.notebooks if n.name == name]
        carnet = candidat
    choice = _pass_choice(
        listing, candidat, carnet, mode, sorties, sorties_vu, plafond, plafond_auto
    )
    planned = (
        gpu.plan(
            path,
            [n.file for n in choice.notebooks],
            short=choice.short,
            write_outputs=choice.write_outputs,
        )
        if choice.notebooks
        else gpu.Plan()
    )
    busy = next((job for job in _gpu_jobs(studio, path) if _is_pass(job)), None)
    return _render(
        request,
        "_gpu.html",
        workspace=found,
        listing=listing,
        choice=choice,
        plan=planned,
        last={n.file: n.last_seconds for n in planned.notebooks},
        ceiling=planned.ceiling(choice.ceiling),
        auto_ceiling=planned.ceiling(None),
        busy=busy,
        kinds=labs.KINDS,
    )


def _gpu_jobs(studio: Studio, path: Path) -> list[Job]:
    return [
        job for job in studio.jobs.jobs(path) if job.lane == "gpu" and not job.finished
    ]


def _is_pass(job: Job) -> bool:
    return job.steps[0][1:4] == ("labs", "gpu", "pass")


@router.post("/espaces/{name}/gpu/lancer", response_class=HTMLResponse)
def gpu_start(
    request: Request,
    studio: StudioDep,
    name: str,
    carnet: Files = None,
    mode: Annotated[str, Form()] = "complet",
    sorties: Annotated[str | None, Form()] = None,
    sorties_vu: Annotated[str | None, Form()] = None,
    plafond: Annotated[float | None, Form()] = None,
) -> Response:
    """Start the GPU pass the modal confirmed, as a job of the GPU lane.

    Returns:
        The job.

    Raises:
        HTTPException: 422 without a notebook or a ceiling.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    choice = _pass_choice(
        labs.listing(path), None, carnet, mode, sorties, sorties_vu, plafond, None
    )
    if not choice.notebooks or choice.ceiling is None:
        raise HTTPException(422, "Choisissez au moins un notebook, et un plafond")
    files = [notebook.file for notebook in choice.notebooks]
    shown = sorted({notebook.name for notebook in choice.notebooks})
    first = choice.notebooks[0]
    link = (
        (
            "Voir l'avant/après",
            f"/espaces/{name}/tp/{first.name}?lang={first.language}&vue=avant-apres",
        )
        if choice.write_outputs
        else None
    )
    studio.jobs.submit(
        path,
        f"Exécuter sur GPU {', '.join(shown)}"
        f" ({'courte' if choice.short else 'complète'}"
        f"{', sorties enregistrées' if choice.write_outputs else ''})",
        gpu.pass_steps(
            path,
            files,
            short=choice.short,
            write_outputs=choice.write_outputs,
            max_hours=choice.ceiling,
        ),
        form=f"/espaces/{name}/gpu/formulaire?"
        + "&".join(f"carnet={quote(file)}" for file in files),
        lane="gpu",
        link=link,
        needs_memory=False,
    )
    return _started(request, found)


@router.get("/espaces/{name}/gpu/resume", response_class=HTMLResponse)
def gpu_badge(request: Request, studio: StudioDep, name: str) -> Response:
    """The status bar's item while a machine bills, like VS Code's remote one.

    Returns:
        Each machine's GPU, time and cost so far; nothing without one.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    return _render(
        request,
        "_gpu_badge.html",
        workspace=found,
        found=gpu.machines(path),
        renting=any(_is_pass(job) for job in _gpu_jobs(studio, path)),
        now=datetime.now(UTC),
    )


def _gpu_machines(
    request: Request, studio: Studio, name: str, **context: Any
) -> Response:
    found = studio.workspace(name)
    path = found.worktree.path
    running = next((job for job in _gpu_jobs(studio, path) if _is_pass(job)), None)
    return _render(
        request,
        "_gpu_machines.html",
        workspace=found,
        found=gpu.machines(path),
        running=running,
        now=datetime.now(UTC),
        **context,
    )


@router.post("/espaces/{name}/gpu/machines", response_class=HTMLResponse)
def gpu_machines(request: Request, studio: StudioDep, name: str) -> Response:
    """The machines billing, the pass running one, and "Arrêter la machine".

    Returns:
        The dialog's content.
    """
    return _gpu_machines(request, studio, name)


@router.post("/espaces/{name}/gpu/arreter", response_class=HTMLResponse)
def gpu_stop(
    request: Request,
    studio: StudioDep,
    name: str,
    machine: Annotated[str, Form()] = gpu.MACHINE,
    confirme: Annotated[str | None, Form()] = None,
) -> Response:
    """Stop a machine: the pass running it if any, else `deckz labs gpu down`.

    A pass stopped destroys its machine itself; its runs in progress are
    lost, so that is asked first. A machine no pass runs (a crash left it,
    a terminal rented it) is destroyed at once.

    Returns:
        The question, the dialog once the pass was told to stop, or the \
        job destroying the machine.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    running = next((job for job in _gpu_jobs(studio, path) if _is_pass(job)), None)
    if running is not None:
        if confirme is None:
            return _gpu_machines(request, studio, name, asking=True)
        studio.jobs.stop(path, running.id)
        response = _gpu_machines(request, studio, name, stopping=True)
        response.headers["HX-Trigger-After-Settle"] = "jobs-changed"
        return response
    studio.jobs.submit(
        path,
        f"Arrêter la machine GPU {machine}",
        gpu.down_steps(path, machine),
        rerun=True,
        lane="gpu",
        needs_memory=False,
    )
    return _started(request, found)


def _agent_entry(entry: agent.Entry) -> str:
    return templates.get_template("_agent_entry.html").render(entry=entry)


def _agent_question(question: agent.Question | None) -> str:
    if question is None:
        return ""
    return templates.get_template("_agent_question.html").render(
        question=question, other=agent.OTHER
    )


@router.get("/espaces/{name}/agent/evenements")
async def agent_events(
    request: Request, studio: StudioDep, name: str
) -> StreamingResponse:
    """The workspace's conversation, as it goes.

    Returns:
        Server-sent events: `reset` then an `entry` per line of the \
        transcript (its HTML), `state` (whether the agent works or waits \
        for an answer, whether Claude Code is logged in), `question` (the \
        form of the question the agent waits on, empty once answered), and \
        the next entries as they come.
    """
    found = studio.workspace(name)
    conversation = studio.agents.conversation(found.worktree.path)

    async def stream() -> AsyncIterator[str]:
        sent = 0
        quiet = 0.0
        last_state: dict[str, object] | None = None
        last_question: int | None = None
        yield _event("reset", {})
        while not await studio.gone(request):
            if len(conversation.entries) < sent:
                sent = 0
                yield _event("reset", {})
            for entry in conversation.entries[sent:]:
                yield _event("entry", {"html": _agent_entry(entry)})
            sent = len(conversation.entries)
            ok, account = await studio.login.status()
            question = conversation.question
            if (question_id := question.id if question else None) != last_question:
                last_question = question_id
                yield _event("question", {"html": _agent_question(question)})
            state: dict[str, object] = {
                "running": conversation.running,
                "asking": question is not None,
                "usage": agent.usage_summary(conversation.account.windows),
                "pausedUntil": agent.when(conversation.paused_until)
                if conversation.paused_until
                else "",
                "undoable": len(conversation.undoable.files)
                if conversation.undoable
                else 0,
                "loggedIn": ok,
                "account": account,
            }
            if state != last_state:
                last_state = state
                yield _event("state", state)
            version = conversation.version
            # Not longer than a second: studioz may be stopping.
            await conversation.wait(version, 1.0)
            quiet = quiet + 1.0 if conversation.version == version else 0.0
            if quiet >= _HEARTBEAT:
                quiet = 0.0
                yield ": heartbeat\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/espaces/{name}/agent/message")
async def agent_message(
    studio: StudioDep, name: str, message: Annotated[str, Form()] = ""
) -> Response:
    """Give the agent a message.

    Returns:
        204, or 409 while the agent is at work or Claude Code isn't logged in.
    """
    found = studio.workspace(name)
    ok, why = await studio.login.status()
    if not ok:
        return JSONResponse({"error": why}, status_code=409)
    conversation = studio.agents.conversation(found.worktree.path)
    # A browser posts a form's text with CRLF line endings.
    if not await conversation.send(message.replace("\r\n", "\n")):
        return JSONResponse({"error": "L'agent travaille encore"}, status_code=409)
    return Response(status_code=204)


@router.post("/espaces/{name}/agent/reponse")
async def agent_answer(request: Request, studio: StudioDep, name: str) -> Response:
    """Answer the question the agent waits on (`_agent_question.html`'s form).

    Returns:
        204, 422 when a question has no answer, or 409 when the question \
        doesn't wait anymore.
    """
    found = studio.workspace(name)
    conversation = studio.agents.conversation(found.worktree.path)
    form = await request.form()
    question = conversation.question
    if question is None or str(question.id) != form.get("question"):
        return JSONResponse(
            {"error": "Cette question n'attend plus de réponse"}, status_code=409
        )
    answers = {
        asked.question: asked.answer(
            [str(v) for v in form.getlist(f"q{i}")], str(form.get(f"q{i}-autre", ""))
        )
        for i, asked in enumerate(question.asked)
    }
    if missing := [q for q, a in answers.items() if not a]:
        return JSONResponse(
            {"error": f"Pas de réponse à « {missing[0]} »"}, status_code=422
        )
    if question.deferred:
        # The answers start Claude Code again, resuming the session.
        ok, why = await studio.login.status()
        if not ok:
            return JSONResponse({"error": why}, status_code=409)
    if not await conversation.answer(question.id, answers):
        return JSONResponse(
            {"error": "Cette question n'attend plus de réponse"}, status_code=409
        )
    return Response(status_code=204)


@router.post("/espaces/{name}/agent/demander")
async def agent_ask(request: Request, studio: StudioDep, name: str) -> Response:
    """Send the agent what a dialog's "Demander à l'agent" asks (`asks.prompt`).

    Returns:
        204, 422 for an unknown request, or 409 while the agent is at work \
        or Claude Code isn't logged in.
    """
    found = studio.workspace(name)
    form = await request.form()
    values = {key: [str(v) for v in form.getlist(key)] for key in form}
    task = str(form.get("task", ""))
    try:
        text = asks.prompt(task, values)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=422)
    ok, why = await studio.login.status()
    if not ok:
        return JSONResponse({"error": why}, status_code=409)
    conversation = studio.agents.conversation(found.worktree.path)
    if not await conversation.send(text):
        return JSONResponse({"error": "L'agent travaille encore"}, status_code=409)
    return Response(status_code=204)


@router.post("/espaces/{name}/workflows", response_class=HTMLResponse)
def workflows_list(
    request: Request, studio: StudioDep, name: str, formation: Formation = ""
) -> Response:
    """The workflows offered on a deck's page: the deck's, then the others.

    Returns:
        The "Avec l'agent" dialog's content.
    """
    found = studio.workspace(name)
    return _render(
        request,
        "_workflows.html",
        workspace=found,
        declared=workflows.declared(found.worktree.path),
        deck=formation,
    )


@dataclass(frozen=True)
class _Answers:
    """A workflow's form, as posted."""

    values: dict[str, str]
    """The text fields'."""
    deck: str
    files: dict[str, tuple[str, bytes]]
    """The file fields given: their name and content."""
    fresh: bool
    """Whether to start a new conversation."""
    formation: str
    """The deck on screen, which the form is about."""
    name: str
    """The new workspace's name, from the home page; empty to derive one."""
    too_large: str | None = None
    """A file over `workflows.MAX_FILE_SIZE`, not read."""

    @classmethod
    def empty(cls, formation: str = "") -> "_Answers":
        return cls({}, formation, {}, False, formation, "")


async def _answers(request: Request, workflow: workflows.Workflow) -> _Answers:
    form = await request.form()
    files: dict[str, tuple[str, bytes]] = {}
    too_large = None
    for one in workflow.inputs:
        upload = form.get(one.name)
        if one.kind == "file" and isinstance(upload, UploadFile) and upload.filename:
            data = await upload.read(workflows.MAX_FILE_SIZE + 1)
            if len(data) > workflows.MAX_FILE_SIZE:
                too_large = upload.filename
            else:
                files[one.name] = (upload.filename, data)
    return _Answers(
        {
            one.name: str(form.get(one.name, "")).replace("\r\n", "\n").strip()
            for one in workflow.inputs
            if one.kind != "file"
        },
        str(form.get("deck", "")),
        files,
        form.get("nouvelle") == "1",
        str(form.get("formation", "")),
        str(form.get("espace", "")).strip(),
        too_large,
    )


def _workflow_form(
    request: Request,
    studio: Studio,
    workflow: workflows.Workflow,
    declared: workflows.Declared,
    found: workspaces.Workspace | None,
    answers: _Answers,
    **context: Any,
) -> Response:
    """A workflow's form, in a workspace, or creating one if `found` is None.

    Returns:
        The dialog's content.
    """
    scoped = workflow.scope == "deck"
    if found is None:
        action = f"/workflows/{workflow.key}"
        decks = workflows.decks_at(studio.main) if scoped else []
    else:
        action = f"/espaces/{quote(found.name)}/workflows/{workflow.key}"
        decks = workspaces.decks(found.worktree.path) if scoped else []
    return _render(
        request,
        "_workflow.html",
        action=action,
        workspace=found,
        workflow=workflow,
        missing=declared.missing.get(workflow.key),
        decks=decks,
        conversation=found is not None
        and bool(studio.agents.conversation(found.worktree.path).entries),
        answers=answers,
        base=workspaces.base_name(studio.main),
        **context,
    )


async def _refusal(
    studio: Studio,
    workflow: workflows.Workflow,
    declared: workflows.Declared,
    answers: _Answers,
    decks: list[str],
) -> str | None:
    """Why the workflow can't start with `answers`.

    Returns:
        What to fix, None if nothing.
    """
    if skill := declared.missing.get(workflow.key):
        return f"La skill « {skill} » n'existe pas dans cet espace."
    if answers.too_large:
        return f"« {answers.too_large} » dépasse 100 Mo."
    given = set(answers.files)
    if lacking := workflow.refusal(answers.values, given, answers.deck, decks):
        return lacking
    ok, why = await studio.login.status()
    return None if ok else why


async def _begin(
    studio: Studio, path: Path, workflow: workflows.Workflow, answers: _Answers
) -> str | None:
    """Start the workflow in the workspace `path`: its files kept, its turn sent.

    Returns:
        Why it didn't start, None if it did.
    """
    conversation = studio.agents.conversation(path)
    busy = "L'agent travaille encore : attendez la fin de son tour."
    if conversation.running:
        return busy
    values = dict(answers.values)
    for input_name, (filename, data) in answers.files.items():
        values[input_name] = await asyncio.to_thread(
            workflows.keep_file, path, filename, data
        )
    if answers.fresh:
        await conversation.reset()
    report = (
        workflows.start_report(path, workflow, answers.deck)
        if workflow.report
        else None
    )
    prompt, shown = workflow.message({**values, workflows.DECK: answers.deck}, report)
    return None if await conversation.send(prompt, shown) else busy


def _declared_workflow(
    studio: Studio, name: str, key: str
) -> tuple[workspaces.Workspace, workflows.Workflow, workflows.Declared]:
    found = studio.workspace(name)
    declared = workflows.declared(found.worktree.path)
    workflow = declared.get(key)
    if workflow is None:
        raise HTTPException(404, f"Pas de workflow « {key} » dans « {name} »")
    return found, workflow, declared


@router.post("/espaces/{name}/workflows/{key}/formulaire", response_class=HTMLResponse)
def workflow_form(
    request: Request, studio: StudioDep, name: str, key: str, formation: Formation = ""
) -> Response:
    """A workflow's form, about the deck on screen if it's a deck's workflow.

    Returns:
        The dialog's content.
    """
    found, workflow, declared = _declared_workflow(studio, name, key)
    return _workflow_form(
        request, studio, workflow, declared, found, _Answers.empty(formation)
    )


@router.post("/espaces/{name}/workflows/{key}", response_class=HTMLResponse)
async def workflow_start(
    request: Request, studio: StudioDep, name: str, key: str
) -> Response:
    """Start a workflow: its prompt, filled in, begins a turn of the agent.

    Returns:
        Nothing to show, telling the page (`agent-started`) to close the \
        dialog and open the agent's panel; or the form again with what's \
        wrong, the answers kept but the files.
    """
    found, workflow, declared = _declared_workflow(studio, name, key)
    path = found.worktree.path
    answers = await _answers(request, workflow)
    decks = workspaces.decks(path) if workflow.scope == "deck" else []
    error = await _refusal(studio, workflow, declared, answers, decks)
    if error is None:
        error = await _begin(studio, path, workflow, answers)
    if error is not None:
        return _workflow_form(
            request,
            studio,
            workflow,
            declared,
            found,
            answers,
            dropped=bool(answers.files),
            error=error,
        )
    return Response(headers={"HX-Trigger": "agent-started", "HX-Reswap": "none"})


def _home_workflow(
    studio: Studio, key: str
) -> tuple[workflows.Workflow, workflows.Declared]:
    declared = workflows.declared_at(studio.main)
    workflow = declared.get(key)
    if workflow is None:
        raise HTTPException(404, f"Pas de workflow « {key} »")
    return workflow, declared


@router.post("/workflows/{key}/formulaire", response_class=HTMLResponse)
def home_workflow_form(request: Request, studio: StudioDep, key: str) -> Response:
    """A workflow's form on the home page: it opens a new workspace.

    Returns:
        The dialog's content.
    """
    workflow, declared = _home_workflow(studio, key)
    return _workflow_form(request, studio, workflow, declared, None, _Answers.empty())


@router.post("/workflows/{key}", response_class=HTMLResponse)
async def home_workflow_start(
    request: Request, studio: StudioDep, key: str
) -> Response:
    """Open a new workspace, and start the workflow there.

    Its name is the one given, else one made from the deck or the workflow.

    Returns:
        A redirection to the workspace (to the deck's page for a deck's \
        workflow), its agent's panel open; or the form again with what's \
        wrong; or what its installation left missing, the workflow not \
        started.
    """
    workflow, declared = _home_workflow(studio, key)
    answers = await _answers(request, workflow)
    decks = workflows.decks_at(studio.main) if workflow.scope == "deck" else []
    error = await _refusal(studio, workflow, declared, answers, decks)
    created = None
    if error is None:
        name = answers.name or workspaces.free_name(
            studio.main, Path(answers.deck).name or workflow.key
        )
        try:
            created = await asyncio.to_thread(workspaces.create, studio.settings, name)
        except DeckzError as failure:
            error = str(failure)
    if created is None:
        return _workflow_form(
            request,
            studio,
            workflow,
            declared,
            None,
            answers,
            dropped=bool(answers.files),
            error=error,
        )
    if not created.ready:
        return _render(request, "_setup.html", created=created, workflow=workflow)
    # The workspace starts from the commit the form was read from, and its
    # agent is idle: nothing keeps the workflow from starting.
    await _begin(studio, created.path, workflow, answers)
    target = f"/espaces/{quote(created.name)}"
    if workflow.scope == "deck":
        target += f"/formations/{quote(answers.deck)}"
    return Response(headers={"HX-Redirect": f"{target}?agent=1"})


@router.get("/espaces/{name}/traductions", response_class=HTMLResponse)
def backlog_panel(
    request: Request, studio: StudioDep, name: str, formation: str = ""
) -> Response:
    """The navigator's "À traduire" panel: the workspace's translation backlog.

    Returns:
        The panel, which reloads itself while `deckz i18n stale` runs, and \
        on a `workspace-changed` event (a commit moves HEAD).
    """
    found = studio.workspace(name)
    return _render(
        request,
        "_backlog.html",
        workspace=found,
        report=studio.backlog.report(found.worktree.path),
        deck=formation,
    )


def _nothing_to_port_dialog(
    request: Request,
    studio: Studio,
    found: workspaces.Workspace,
    path: str,
    **context: Any,
) -> Response:
    return _render(
        request,
        "_nothing_to_port.html",
        workspace=found,
        path=path,
        stale=studio.backlog.find(found.worktree.path, path),
        **context,
    )


@router.post(
    "/espaces/{name}/traductions/rien-a-porter/formulaire",
    response_class=HTMLResponse,
)
def nothing_to_port_form(
    request: Request, studio: StudioDep, name: str, path: Annotated[str, Form()]
) -> Response:
    """Ask why a backlog entry's changes need no port.

    Returns:
        The dialog's content.
    """
    return _nothing_to_port_dialog(request, studio, studio.workspace(name), path)


@router.post("/espaces/{name}/traductions/rien-a-porter", response_class=HTMLResponse)
def nothing_to_port(
    request: Request,
    studio: StudioDep,
    name: str,
    path: Annotated[str, Form()],
    reason: Annotated[str, Form()] = "",
) -> Response:
    """Take a backlog entry off: `deckz i18n mark-synced`, an empty commit.

    Returns:
        The dialog, with what deckz said; on a commit, telling the page \
        (`workspace-changed`), so that the panels follow.
    """
    found = studio.workspace(name)
    workspace = found.worktree.path
    reason = " ".join(reason.split())
    if not reason:
        return _nothing_to_port_dialog(
            request,
            studio,
            found,
            path,
            error="Dites pourquoi il n'y a rien à porter.",
        )
    before = head(workspace)
    marked = studio.backlog.mark_synced(workspace, path, reason)
    if not marked.ok:
        return _nothing_to_port_dialog(
            request, studio, found, path, reason=reason, refused=marked.output
        )
    carry_over(workspace, before, head(workspace))
    response = _nothing_to_port_dialog(request, studio, found, path, done=marked.output)
    response.headers["HX-Trigger"] = "workspace-changed"
    return response


@router.get("/espaces/{name}/rapports", response_class=HTMLResponse)
def reports_panel(
    request: Request, studio: StudioDep, name: str, formation: str = ""
) -> Response:
    """The navigator's Rapports panel: the workflows' reports.

    Returns:
        The panel, empty when there's none.
    """
    found = studio.workspace(name)
    path = found.worktree.path
    declared = workflows.declared(path)
    conversation = studio.agents.conversation(path)
    return _render(
        request,
        "_reports.html",
        workspace=found,
        reports=workflows.reports(path),
        declared=declared,
        running=conversation.running,
        deck=formation,
    )


def _report(
    studio: Studio, name: str, report_id: str
) -> tuple[workspaces.Workspace, workflows.Report]:
    found = studio.workspace(name)
    report = workflows.report(found.worktree.path, report_id)
    if report is None:
        raise HTTPException(404, f"Pas de rapport « {report_id} » dans « {name} »")
    return found, report


def _report_dialog(
    request: Request,
    studio: Studio,
    found: workspaces.Workspace,
    report: workflows.Report,
    **context: Any,
) -> Response:
    workflow = workflows.declared(found.worktree.path).get(report.workflow)
    return _render(
        request,
        "_report.html",
        workspace=found,
        report=report,
        parts=report.parts() if report.path.is_file() else [],
        workflow=workflow,
        **context,
    )


@router.post("/espaces/{name}/rapports/{report_id}", response_class=HTMLResponse)
def report_dialog(
    request: Request, studio: StudioDep, name: str, report_id: str
) -> Response:
    """A report's findings, each a box to tick, and what to do with them.

    Returns:
        The dialog's content.
    """
    found, report = _report(studio, name, report_id)
    return _report_dialog(request, studio, found, report)


def _ticked(form: Any) -> set[int]:
    return {int(value) for value in form.getlist("item") if str(value).isdigit()}


@router.post("/espaces/{name}/rapports/{report_id}/coches")
async def report_ticks(
    request: Request, studio: StudioDep, name: str, report_id: str
) -> Response:
    """Keep the findings ticked, in the report's file.

    Returns:
        204.
    """
    _, report = _report(studio, name, report_id)
    if report.path.is_file():
        workflows.tick(report.path, _ticked(await request.form()))
    return Response(status_code=204)


@router.post("/espaces/{name}/rapports/{report_id}/suite", response_class=HTMLResponse)
async def report_then(
    request: Request, studio: StudioDep, name: str, report_id: str
) -> Response:
    """Send the agent the workflow's `then`, with the findings ticked.

    Returns:
        Nothing to show, telling the page (`agent-started`); or the dialog \
        again with why not.
    """
    found, report = _report(studio, name, report_id)
    path = found.worktree.path
    workflow = workflows.declared(path).get(report.workflow)

    def refuse(error: str) -> Response:
        return _report_dialog(request, studio, found, report, error=error)

    if workflow is None or workflow.then is None:
        return refuse("Ce workflow ne propose plus de suite (deckz.yml a changé).")
    if not report.path.is_file():
        return refuse("L'agent n'a pas encore écrit ce rapport.")
    workflows.tick(report.path, _ticked(await request.form()))
    chosen = report.chosen()
    if not chosen:
        return refuse("Cochez au moins un constat.")
    ok, why = await studio.login.status()
    if not ok:
        return refuse(why)
    prompt, shown = workflow.then.message(
        {
            workflows.DECK: report.deck,
            workflows.CHOSEN: "\n".join(
                "- " + item.text.replace("\n", "\n  ") for item in chosen
            ),
            workflows.REPORT: report.relative,
        }
    )
    if not await studio.agents.conversation(path).send(prompt, shown):
        return refuse("L'agent travaille encore : attendez la fin de son tour.")
    return Response(headers={"HX-Trigger": "agent-started", "HX-Reswap": "none"})


@router.post("/espaces/{name}/agent/annuler")
async def agent_undo(studio: StudioDep, name: str) -> Response:
    """Put back the files the agent's last turn changed.

    Returns:
        204, or 409 with why not (a turn running, a commit since).
    """
    found = studio.workspace(name)
    refused = await studio.agents.conversation(found.worktree.path).undo()
    if refused is not None:
        return JSONResponse({"error": refused}, status_code=409)
    return Response(status_code=204)


@router.post("/espaces/{name}/agent/arreter")
async def agent_stop(studio: StudioDep, name: str) -> Response:
    found = studio.workspace(name)
    await studio.agents.conversation(found.worktree.path).interrupt()
    return Response(status_code=204)


@router.post("/espaces/{name}/agent/nouvelle")
async def agent_reset(studio: StudioDep, name: str) -> Response:
    found = studio.workspace(name)
    await studio.agents.conversation(found.worktree.path).reset()
    return Response(status_code=204)


@router.get("/espaces/{name}/taille", response_class=HTMLResponse)
def size(studio: StudioDep, name: str) -> str:
    return _size(workspaces.size(studio.workspace(name).worktree.path))


@router.post("/espaces/{name}/fermer", response_class=HTMLResponse)
def close(
    request: Request,
    studio: StudioDep,
    name: str,
    force: Annotated[bool, Form()] = False,
) -> Response:
    found = studio.workspace(name)
    try:
        kept = remove(studio.settings, name, force=force)
    except WorktreeError:
        return _render(request, "_close_refused.html", workspace=found)
    return _render(request, "_closed.html", workspace=found, kept=kept)


async def _stop_idle(studio: Studio) -> None:
    while True:
        await asyncio.sleep(5)
        await asyncio.to_thread(studio.watches.stop_idle)
        await studio.agents.stop_idle()


def create_app(
    repository: Path,
    watches: Watches | None = None,
    statuses: problems.Statuses | None = None,
    affected: changes.Affected | None = None,
    baselines: Baselines | None = None,
    agents: agent.Agents | None = None,
    login: Login | None = None,
    drafter: Callable[[Path, list[str]], Awaitable[str]] | None = None,
    backlog: Backlog | None = None,
    jobs: Jobs | None = None,
) -> FastAPI:
    """The studioz application for the deckz repository `repository`.

    Args:
        repository: Any checkout of the repository.
        watches: The live builds' manager (tests replace deckz's command).
        statuses: The workspaces' `deckz status` runs (tests replace it too).
        affected: The workspaces' `deckz show affected` runs (same).
        baselines: The baselines' builds (same).
        agents: The workspaces' agents (tests replace the Agent SDK's client).
        login: Claude Code's login check (same).
        drafter: What writes a commit message (same).
        backlog: The workspaces' `deckz i18n stale` runs (same).
        jobs: The jobs, holding back those needing memory under their \
            threshold (`studioz --min-free-memory`; tests replace the memory).

    Returns:
        The application.
    """
    main = main_checkout(repository)
    settings = GlobalSettings.from_yaml(main)
    paths = settings.paths
    studio = Studio(
        main,
        settings,
        watches or Watches(),
        statuses
        or problems.Statuses(
            workspaces.base_branch(main),
            videos_dir=paths.videos_dir.relative_to(paths.git_dir),
            labs_dir=paths.labs_notebooks_dir.relative_to(paths.git_dir),
        ),
        affected or changes.Affected(),
        baselines or Baselines(),
        changes.LangPairs(),
        backlog or Backlog(),
        jobs or Jobs(),
        agents or agent.Agents(),
        login or Login(),
        drafter or asks.draft_message,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        reaper = asyncio.create_task(_stop_idle(studio))
        try:
            yield
        finally:
            reaper.cancel()
            with suppress(asyncio.CancelledError):
                await reaper
            await asyncio.to_thread(studio.watches.stop_all)
            studio.statuses.stop_all()
            studio.affected.stop_all()
            studio.backlog.stop_all()
            await asyncio.to_thread(studio.jobs.stop_all)
            await studio.agents.close_all()
            await asyncio.to_thread(studio.baselines.stop_all)

    app = FastAPI(
        title="studioz",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.studio = studio
    app.add_middleware(LocalOnly)
    app.mount("/static", _Static(directory=_PACKAGE / "static"), name="static")
    app.include_router(router)
    return app
