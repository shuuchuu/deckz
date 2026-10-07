from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from ..exceptions import MissingExtraError

# Top-level modules only provided by each optional-dependency group, keyed by
# the group's name in `[project.optional-dependencies]`.
_EXTRA_MODULES: Mapping[str, frozenset[str]] = {
    "extras": frozenset(
        {
            "email_validator",
            "google",
            "google_auth_oauthlib",
            "googleapiclient",
            "niquests",
            "sendgrid",
        }
    ),
    "labs": frozenset({"PIL"}),
    "parity": frozenset({"PIL", "playwright", "pypdfium2"}),
}


@contextmanager
def extras_imports(extra: str = "extras") -> Iterator[None]:
    """Turn a missing optional dependency into a user-facing error.

    Wrap the imports of an extras-backed command with it. Any other import
    error is re-raised untouched.

    Args:
        extra: Name of the `[project.optional-dependencies]` group the \
            wrapped imports belong to.

    Raises:
        ImportError: If the failing import isn't an optional dependency.
        MissingExtraError: If an optional dependency failed to import.
    """
    try:
        yield
    except ImportError as e:
        # pydantic's EmailStr raises a plain ImportError chained to the
        # underlying ModuleNotFoundError.
        missing = e.name or getattr(e.__cause__, "name", None) or ""
        if missing.partition(".")[0] not in _EXTRA_MODULES.get(extra, frozenset()):
            raise
        msg = (
            f"this command needs the optional dependency {missing!r}, "
            f'install it with `pip install "deckz[{extra}]"`'
        )
        raise MissingExtraError(msg) from e
