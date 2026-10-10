"""Refuse requests that don't come from studioz's own pages.

studioz listens on localhost only, but any page open in the person's browser
can still send requests there: a form posted to `http://localhost:<port>`
(cross-site request forgery), or a domain of its own resolved to 127.0.0.1
(DNS rebinding). Either would let a website create workspaces, commit or
push in the person's name. So a request must name a local host, and one that
changes something must come from a page of that same origin.
"""

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(host: str) -> str:
    return urlsplit(f"//{host}").hostname or ""


async def local_only(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    host = request.headers.get("host", "")
    if _hostname(host) not in LOCAL_HOSTS:
        return PlainTextResponse("studioz only answers on localhost", 403)
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin != f"{request.url.scheme}://{host}":
            return PlainTextResponse("request from another site refused", 403)
    return await call_next(request)
