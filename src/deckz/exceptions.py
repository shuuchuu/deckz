from collections.abc import Sequence
from dataclasses import dataclass

from .models import Deck


class DeckzError(Exception):
    pass


class UnresolvableFileError(DeckzError):
    pass


class UnresolvableSectionError(DeckzError):
    pass


class GitRepositoryNotFoundError(DeckzError):
    pass


class SectionNotFoundError(DeckzError):
    pass


class FlavorNotFoundError(DeckzError):
    pass


class FlavorAlreadyExistsError(DeckzError):
    pass


class InvalidConfigurationError(DeckzError):
    """A yaml file of the deckz-managed repo is missing, unparsable or invalid."""


class MissingExtraError(DeckzError):
    """A command needs an optional dependency that isn't installed."""


class HookError(DeckzError):
    """A Python hook of the deckz-managed repo is missing, broken or misbehaves."""


class HookInstallRefusedError(DeckzError):
    """`deckz hooks install` refuses to overwrite a git hook it didn't write."""


class CommitRefusedError(DeckzError):
    """A git hook deckz installed (`deckz hooks check-commit-msg`) refuses a commit."""


class CompilationError(DeckzError):
    pass


@dataclass(frozen=True)
class BuildFailure:
    """A deck that failed to build in a language, and why."""

    label: str
    lang: str
    errors: tuple[tuple[str, str], ...]
    """Each failure: the compilation's name and the compiler's errors, or \
    the step that failed (a content file's render) and its message."""


class BuildsFailedError(CompilationError):
    """Decks of a `keep_going` build failed: `failures` says how, each."""

    def __init__(self, message: str, failures: Sequence[BuildFailure]) -> None:
        super().__init__(message)
        self.failures = tuple(failures)


class RenderError(DeckzError):
    """A content file's Jinja template failed to render."""


class ScaffoldRefusedError(DeckzError):
    """`deckz new`/`deckz labs new` would overwrite something, or got a bad name."""


class LabIdConflictError(DeckzError):
    """`deckz labs ids` found a duplicate or already-taken notebook ID."""


class LabContainerError(DeckzError):
    """`deckz labs check --container` can't build or start the dev container."""


class LabPublishRefusedError(DeckzError):
    """`deckz labs publish` refuses to publish.

    Uncommitted changes, an invalid or duplicate ID, or it would drop an \
    already-published notebook.
    """


class LabOutputsMismatchError(DeckzError):
    """`deckz labs outputs` was given an executed copy with a different cell count."""


class LabOutputsHookError(DeckzError):
    """A `labs.outputs.hooks` command failed on a notebook just written."""


class GpuRunError(DeckzError):
    """`deckz labs gpu` failed: no machine rented or booted, or a remote step failed."""


class VideoSceneError(DeckzError):
    """A `@register_scene` class is declared in a way deckz can't parse."""


class VideoFetchError(DeckzError):
    """`deckz videos fetch` can't fetch the published renders."""


class VideoPublishRefusedError(DeckzError):
    """`deckz videos publish` refuses to publish.

    Uncommitted scene changes, a render missing/stale/at the wrong quality, \
    one over the publish size limit, or it would drop an already-published \
    video.
    """


class RemoteError(DeckzError):
    """A git remote `deckz labs publish`/`videos publish` pushes to is missing.

    Or it can't be reached, or it refuses the push.
    """


class WorktreeError(DeckzError):
    """`deckz worktree` refuses.

    An invalid or taken name, or removing a worktree holding work nothing \
    else has (uncommitted changes, commits on no other branch).
    """


class DeckParsingError(DeckzError):
    """Some nodes of `deck` failed to parse, each described in `errors`."""

    def __init__(self, deck: Deck, errors: list[str]) -> None:
        super().__init__(f"deck parsing failed: {'; '.join(errors)}")
        self.deck = deck
        self.errors = errors


class CourseNotesError(DeckzError):
    """A deck's course notes can't be built, e.g. no chapter is written yet."""
