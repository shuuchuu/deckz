class DeckzError(Exception):
    pass


class UnresolvableFileError(DeckzError):
    pass


class UnresolvableSectionError(DeckzError):
    pass


class GitRepositoryNotFoundError(DeckzError):
    pass
