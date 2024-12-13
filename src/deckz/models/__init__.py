"""Modules containing model classes for different parts of deckz.

The intent is that the classes defined in this package should not end up containing \
too much logic. However some logic is still present, when writing it elsewhere seemed \
worse than not respecting this intent 100%.

- [`deck`][deckz.models.deck] contains models that represent parsed decks and their \
    constituents
- [`definitions`][deckz.models.definitions] contains models that represent decks \
    definitions
- [`scalars`][deckz.models.scalars] contains models for non-container types. Mostly \
    NewTypes that help disambiguate types that are used a lot in different contexts \
    (e.g. Path and str)
- [`slides`][deckz.models.slides] contains models that are fed to the rendering part \
    of deckz
"""
