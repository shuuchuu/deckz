from argparse import ArgumentParser
from importlib import import_module, invalidate_caches as importlib_invalidate_caches
from logging import getLogger
from pkgutil import walk_packages
from typing import Any, Callable, List, NamedTuple, Optional


_logger = getLogger(__name__)


class Command(NamedTuple):
    name: str
    description: str
    handler: Callable[..., Any]
    parser_definer: Callable[[ArgumentParser], None]


commands: List[Command] = []


def register_command(
    parser_definer: Callable[[ArgumentParser], None] = lambda _: None,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def wrapper(handler: Callable[..., Any]) -> Callable[..., Any]:
        commands.append(
            Command(
                name=handler.__name__.replace("_", "-") if name is None else name,
                description=handler.__doc__.strip().splitlines()[0]
                if description is None
                else description,
                parser_definer=parser_definer,
                handler=handler,
            )
        )
        return handler

    return wrapper


def _import_module_and_submodules(package_name: str) -> None:
    """
    From https://github.com/allenai/allennlp/blob/master/allennlp/common/util.py
    """
    importlib_invalidate_caches()

    module = import_module(package_name)
    path = getattr(module, "__path__", [])
    path_string = "" if not path else path[0]

    for module_finder, name, _ in walk_packages(path):
        if path_string and module_finder.path != path_string:
            continue
        subpackage = f"{package_name}.{name}"
        _import_module_and_submodules(subpackage)


_import_module_and_submodules(__name__)
