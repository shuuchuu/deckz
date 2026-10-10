"""The web application: pages over a deckz repository's workspaces."""

import asyncio
import json
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
from deckz.configuring.settings import DeckSettings, GlobalSettings
from deckz.exceptions import DeckzError, WorktreeError
from deckz.models import Lang
from deckz.worktrees import main_checkout, remove

from . import __version__, sources, workspaces
from .local_only import local_only
from .watches import Snapshot, Watch, Watches, handout

_PACKAGE = Path(str(files("studioz")))

templates = Jinja2Templates(directory=_PACKAGE / "templates")
router = APIRouter()


@dataclass(frozen=True)
class Studio:
    main: Path
    """The repository's main checkout, which studioz never writes to."""
    settings: GlobalSettings
    watches: Watches

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


def _state(snapshot: Snapshot) -> dict[str, object]:
    return {"state": snapshot.state.value, "errors": list(snapshot.errors)}


async def watch_events(
    watch: Watch, pdf_url: str, disconnected: Callable[[], Awaitable[bool]]
) -> AsyncIterator[str]:
    """`watch`'s state and new PDFs as server-sent events, until `disconnected`.

    Following them keeps the watch running.

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
            if (state := _state(snapshot)) != last_state:
                last_state = state
                quiet = 0.0
                yield _event("state", state)
            if snapshot.pdf_version and snapshot.pdf_version != last_pdf:
                last_pdf = snapshot.pdf_version
                quiet = 0.0
                yield _event("pdf", {"url": f"{pdf_url}&v={last_pdf}"})
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
        watch_events(watch, pdf_url, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/espaces/{name}/formations/{deck:path}", response_class=HTMLResponse)
def deck_page(
    request: Request, studio: StudioDep, name: str, deck: str, lang: Lang = "fr"
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


def create_app(repository: Path, watches: Watches | None = None) -> FastAPI:
    """The studioz application for the deckz repository `repository`.

    Args:
        repository: Any checkout of the repository.
        watches: The live builds' manager (tests replace deckz's command).

    Returns:
        The application.
    """
    main = main_checkout(repository)
    studio = Studio(main, GlobalSettings.from_yaml(main), watches or Watches())

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
