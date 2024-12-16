# mypy: disable-error-code="attr-defined"
from abc import ABC
from typing import Any, ClassVar

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


class Config[T](ABC):
    config_key: ClassVar[str]

    @classmethod
    def get_model_class(cls) -> type[T]:
        return cls._registry[cls.config_key][0]


def configurable[T](cls: type[T]) -> type[T]:
    cls._registry = {}

    original_init_subclass = getattr(cls, "__init_subclass__", lambda **kwargs: None)

    def new_init_subclass[U: T](
        subclass: type[U], component: Any, **kwargs: Any
    ) -> None:
        original_init_subclass(**kwargs)
        cls._registry[subclass.config_key] = (component, subclass)

    cls.__init_subclass__ = classmethod(new_init_subclass)  # type: ignore

    def __get_pydantic_core_schema__(  # noqa: N807
        cls_: type[T], source_type: type[Any], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.tagged_union_schema(
            discriminator="config_key",
            choices={
                key: handler(subclass) for key, (_, subclass) in cls._registry.items()
            },
        )

    cls.__get_pydantic_core_schema__ = classmethod(__get_pydantic_core_schema__)

    return cls
