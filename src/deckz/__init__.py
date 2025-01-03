from typing import Any

app_name = "deckz"


def __getattr__(name: str) -> Any:
    """Lazy-load attributes of the deckz package.

    This way of loading is required to avoid loading any code before some important \
    setup is done (such as logging setup). If we were to use a normal syntax to expose \
    the attributes, such as writing

        from .components.assets_building import register_plot

    directly as a top-level module instruction, the entry point (the main function of \
    the deckz.cli.__init__ file) could not setup logging before loading the modules \
    that contain the attributes. That is due to the fact that loading \
    deckz.cli.__init__ entails loading deckz.__init__ first. This cannot be avoided, \
    hence this hack.

    Args:
        name: Name of the attribute to load.

    Raises:
        ValueError: Raised if the name doesn't match a lazy-loadable attribute.

    Returns:
        Lazy-loaded attribute.
    """
    match name:
        case "register_plot":
            from .components.assets_building import register_plot

            return register_plot
        case "register_plotly":
            from .components.assets_building import register_plotly

            return register_plotly
        case _:
            msg = f"cannot find the attribute {name} in module {__name__}"
            raise ValueError(msg)
