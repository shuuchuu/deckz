from pytest import raises

from deckz.exceptions import MissingExtraError
from deckz.extras import extras_imports


def test_missing_extras_module_is_a_user_error() -> None:
    with raises(MissingExtraError, match="deckz\\[extras\\]"), extras_imports():
        raise ModuleNotFoundError(name="sendgrid.helpers")


def test_chained_import_error_is_a_user_error() -> None:
    # Shape of the error pydantic raises for EmailStr without email-validator.
    def fail() -> None:
        try:
            raise ModuleNotFoundError(name="email_validator")
        except ModuleNotFoundError as e:
            msg = "email-validator is not installed"
            raise ImportError(msg) from e

    with raises(MissingExtraError, match="email_validator"), extras_imports():
        fail()


def test_unrelated_import_error_is_reraised() -> None:
    with raises(ModuleNotFoundError), extras_imports():
        raise ModuleNotFoundError(name="deckz.nope")


def test_missing_labs_module_is_a_user_error() -> None:
    with raises(MissingExtraError, match=r"deckz\[labs\]"), extras_imports("labs"):
        raise ModuleNotFoundError(name="PIL")


def test_labs_extra_does_not_catch_extras_modules() -> None:
    with raises(ModuleNotFoundError), extras_imports("labs"):
        raise ModuleNotFoundError(name="sendgrid")
