"""The web application: pages over a deckz repository's workspaces."""

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from deckz.configuring.settings import GlobalSettings
from deckz.exceptions import DeckzError, WorktreeError
from deckz.worktrees import main_checkout, remove

from . import __version__, workspaces
from .local_only import local_only

_PACKAGE = Path(str(files("studioz")))

templates = Jinja2Templates(directory=_PACKAGE / "templates")
router = APIRouter()


@dataclass(frozen=True)
class Studio:
    main: Path
    """The repository's main checkout, which studioz never writes to."""
    settings: GlobalSettings

    def workspace(self, name: str) -> workspaces.Workspace:
        found = workspaces.find(self.settings, name)
        if found is None:
            raise HTTPException(404, f"Pas d'espace de travail « {name} »")
        return found


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


def create_app(repository: Path) -> FastAPI:
    """The studioz application for the deckz repository `repository`.

    Args:
        repository: Any checkout of the repository.

    Returns:
        The application.
    """
    main = main_checkout(repository)
    app = FastAPI(title="studioz", version=__version__, docs_url=None, redoc_url=None)
    app.state.studio = Studio(main, GlobalSettings.from_yaml(main))
    app.middleware("http")(local_only)
    app.mount("/static", StaticFiles(directory=_PACKAGE / "static"), name="static")
    app.include_router(router)
    return app
