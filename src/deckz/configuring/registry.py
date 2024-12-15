# mypy: disable-error-code="attr-defined"
from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


def configurable[T](cls: type[T]) -> type[T]:
    cls._registry = {}

    original_init_subclass = getattr(
        cls, "__init_subclass__", lambda *args, **kwargs: None
    )

    def new_init_subclass[U: T](subclass: type[U], **kwargs: Any) -> None:
        original_init_subclass(**kwargs)
        if hasattr(subclass, "config_key"):
            key = subclass.config_key
            if key in cls._registry:
                msg = (
                    f"trying to use the config_key {key} to register {subclass} but "
                    f"{cls._registry[key]} is already registered at that key."
                )
                raise ValueError(msg)
            cls._registry[key] = subclass

    cls.__init_subclass__ = classmethod(new_init_subclass)  # type: ignore

    def __get_pydantic_core_schema__(  # noqa: N807
        cls_: type[T], source_type: type[Any], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.tagged_union_schema(
            discriminator="registry_key",
            choices={key: handler(subcls) for key, subcls in cls._registry.items()},
        )

    cls.__get_pydantic_core_schema__ = classmethod(__get_pydantic_core_schema__)

    return cls
