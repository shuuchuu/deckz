"""The web application: pages over a deckz repository's workspaces."""

import asyncio
import json
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from deckz.analyzing.frames import frames
from deckz.analyzing.i18n_stale import lang_sync_kind, one_sided
from deckz.configuring.settings import DeckSettings, GlobalSettings
from deckz.exceptions import DeckzError, WorktreeError
from deckz.models import Lang
from deckz.worktrees import main_checkout, remove

from . import (
    __version__,
    background,
    changes,
    commits,
    problems,
    sources,
    sync,
    workspaces,
)
from .baselines import Baselines
from .comparison import compare, signatures
from .local_only import local_only
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
        path = sources.source(found.worktree.path, file)
        if path is None:
            raise HTTPException(404, f"Pas de fichier modifiable « {file} »")
        return path


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


templates.env.filters["ago"] = _ago


@router.get("/", response_class=HTMLResponse)
def home(request: Request, studio: StudioDep) -> Response:
    return _render(
        request,
        "home.html",
        workspaces=workspaces.workspaces(studio.settings),
        upstream=workspaces.upstream(studio.main),
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
            request.is_disconnected,
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
    """The commit dialog, with the fields posted kept.

    Returns:
        Its content, the files changed now listed.
    """
    return _commit_dialog(request, studio, studio.workspace(name), draft)


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


async def _stop_idle_watches(watches: Watches) -> None:
    while True:
        await asyncio.sleep(5)
        await asyncio.to_thread(watches.stop_idle)


def create_app(
    repository: Path,
    watches: Watches | None = None,
    statuses: problems.Statuses | None = None,
    affected: changes.Affected | None = None,
    baselines: Baselines | None = None,
) -> FastAPI:
    """The studioz application for the deckz repository `repository`.

    Args:
        repository: Any checkout of the repository.
        watches: The live builds' manager (tests replace deckz's command).
        statuses: The workspaces' `deckz status` runs (tests replace it too).
        affected: The workspaces' `deckz show affected` runs (same).
        baselines: The baselines' builds (same).

    Returns:
        The application.
    """
    main = main_checkout(repository)
    studio = Studio(
        main,
        GlobalSettings.from_yaml(main),
        watches or Watches(),
        statuses or problems.Statuses(workspaces.base_branch(main)),
        affected or changes.Affected(),
        baselines or Baselines(),
        changes.LangPairs(),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        reaper = asyncio.create_task(_stop_idle_watches(studio.watches))
        try:
            yield
        finally:
            reaper.cancel()
            with suppress(asyncio.CancelledError):
                await reaper
            await asyncio.to_thread(studio.watches.stop_all)
            studio.statuses.stop_all()
            studio.affected.stop_all()
            await asyncio.to_thread(studio.baselines.stop_all)

    app = FastAPI(
        title="studioz",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.studio = studio
    app.middleware("http")(local_only)
    app.mount("/static", StaticFiles(directory=_PACKAGE / "static"), name="static")
    app.include_router(router)
    return app
