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
    def __init__(self, message: str, deck: Deck) -> None:
        super().__init__(message)
        self.deck = deck
