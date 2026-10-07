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


class LabIdConflictError(DeckzError):
    """`deckz labs ids` found a duplicate or already-taken notebook ID."""


class LabPublishRefusedError(DeckzError):
    """`deckz labs publish` refuses to publish.

    Uncommitted changes, an invalid or duplicate ID, or it would drop an \
    already-published notebook.
    """


class LabOutputsMismatchError(DeckzError):
    """`deckz labs outputs` was given an executed copy with a different cell count."""


class DeckParsingError(DeckzError):
    """Some nodes of `deck` failed to parse, each described in `errors`."""

    def __init__(self, deck: Deck, errors: list[str]) -> None:
        super().__init__(f"deck parsing failed: {'; '.join(errors)}")
        self.deck = deck
        self.errors = errors
