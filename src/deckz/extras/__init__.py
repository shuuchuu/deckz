from collections.abc import Iterator
from contextlib import contextmanager

from ..exceptions import MissingExtraError

# Top-level modules only provided by the `deckz[extras]` optional dependencies.
_EXTRAS_MODULES = frozenset(
    {
        "email_validator",
        "google",
        "google_auth_oauthlib",
        "googleapiclient",
        "niquests",
        "sendgrid",
    }
)


@contextmanager
def extras_imports() -> Iterator[None]:
    """Turn a missing `deckz[extras]` dependency into a user-facing error.

    Wrap the imports of an extras-backed command with it. Any other import
    error is re-raised untouched.

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
        if missing.partition(".")[0] not in _EXTRAS_MODULES:
            raise
        msg = (
            f"this command needs the optional dependency {missing!r}, "
            'install it with `pip install "deckz[extras]"`'
        )
        raise MissingExtraError(msg) from e
