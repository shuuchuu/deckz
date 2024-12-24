# mypy: disable-error-code="attr-defined"
# ruff: noqa: SLF001
from abc import ABCMeta
from collections.abc import Callable
from logging import getLogger
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

if TYPE_CHECKING:
    from pydantic import BaseModel

    from .settings import DeckSettings, GlobalSettings

# Cannot use typing.Self in metaclasses for some reason
_Self = TypeVar("_Self", bound="RegistryMeta")
_logger = getLogger(__name__)


class RegistryMeta(ABCMeta):
    registries: ClassVar[dict[str, set[str]]] = {}

    def __new__(
        cls: type[_Self],
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> _Self:
        return super().__new__(cls, name, bases, namespace)

    def __init__(
        cls: _Self,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        key: str | None = None,
        extra_kwargs_class: type["BaseModel"] | None = None,
    ) -> None:
        super().__init__(name, bases, namespace)
        # No registering is done if key is None
        if key is None:
            return
        registry_name: str | None = None
        registry = None
        for base in bases:
            if isinstance(base, RegistryMeta) and hasattr(base, "_registry"):
                registry_name = base._registry_name  # type: ignore
                registry = base._registry
        # Interface, child of GlobalComponent or DeckComponent, parent of
        # implementations
        if registry is None:
            _logger.debug(
                "Creating registry [green]%s[/] based on class %s",
                key,
                cls,
                extra={"markup": True},
            )
            cls._registry: dict[str, tuple[_Self, type[BaseModel] | None]] = {}
            cls._registry_name = key
            RegistryMeta.registries[key] = set()
        # Implementation, child of an interface
        else:
            _logger.debug(
                "Registering %s as [green]%s/%s[/]",
                cls,
                registry_name,
                key,
                extra={"markup": True},
            )
            registry[key] = (cls, extra_kwargs_class)
            assert registry_name is not None
            RegistryMeta.registries[registry_name].add(name)


class _Component(metaclass=RegistryMeta):
    def new_dep[**P, T](
        self,
        cls: Callable[P, T],
        _key: str,
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        return cls._new(_key, self._new_dep_settings, *args, **kwargs)

    @classmethod
    def _new[**P, T](
        cls: Callable[P, T],
        _key: str,
        _settings: "GlobalSettings",
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        (subclass, extra_kwargs_class) = cls._registry[_key]
        conf_dct = getattr(_settings.components, cls._registry_name, {}).get(_key, {})
        extra_kwargs = (
            vars(extra_kwargs_class.model_validate(conf_dct, context=_settings))
            if extra_kwargs_class
            else {}
        )
        _logger.debug(
            "Instantiating class %s from registry entry %s/%s with args %s, kwargs %s "
            "and extra kwargs %s",
            subclass,
            cls._registry_name,
            _key,
            args,
            kwargs,
            extra_kwargs,
        )
        obj = subclass.__new__(subclass)
        obj._new_dep_settings = _settings
        obj.__init__(*args, **kwargs, **extra_kwargs)
        return obj


class GlobalComponent(_Component):
    @classmethod
    def new[**P, T](
        cls: Callable[P, T],
        _key: str,
        _settings: "GlobalSettings",
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        return super()._new(_key, _settings, *args, **kwargs)  # type: ignore


class DeckComponent(_Component):
    @classmethod
    def new[**P, T](
        cls: Callable[P, T],
        _key: str,
        _settings: "DeckSettings",
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        return super()._new(_key, _settings, *args, **kwargs)  # type: ignore
