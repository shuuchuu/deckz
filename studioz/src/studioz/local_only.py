"""Refuse requests that don't come from studioz's own pages.

studioz listens on localhost only, but any page open in the person's browser
can still send requests there: a form posted to `http://localhost:<port>`
(cross-site request forgery), or a domain of its own resolved to 127.0.0.1
(DNS rebinding). Either would let a website create workspaces, commit or
push in the person's name. So a request must name a local host, and one that
changes something must come from a page of that same origin.
"""

from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(host: str) -> str:
    return urlsplit(f"//{host}").hostname or ""


def refused(request: Request) -> str | None:
    """Why `request` is refused.

    Returns:
        The reason, None if it may go through.
    """
    host = request.headers.get("host", "")
    if _hostname(host) not in LOCAL_HOSTS:
        return "studioz only answers on localhost"
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin != f"{request.url.scheme}://{host}":
            return "request from another site refused"
    return None


class LocalOnly:
    """`refused` as a plain ASGI middleware.

    Not Starlette's `BaseHTTPMiddleware`: it would wrap the pages' endless
    server-sent events, and log an error each time a page closes one.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and (reason := refused(Request(scope))):
            await PlainTextResponse(reason, 403)(scope, receive, send)
            return
        await self.app(scope, receive, send)
