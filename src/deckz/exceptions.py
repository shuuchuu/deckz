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


class CompilationError(DeckzError):
    pass


class DeckParsingError(DeckzError):
    """Some nodes of `deck` failed to parse, each described in `errors`."""

    def __init__(self, deck: Deck, errors: list[str]) -> None:
        super().__init__(f"deck parsing failed: {'; '.join(errors)}")
        self.deck = deck
        self.errors = errors
