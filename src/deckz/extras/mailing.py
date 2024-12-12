from pathlib import Path

from pydantic import BaseModel, EmailStr

from ..utils import load_yaml


class MailsConfig(BaseModel):
    api_key: str
    mail: str
    to: dict[str, EmailStr]

    @classmethod
    def from_yaml(cls, path: Path) -> "MailsConfig":
        return cls.model_validate(load_yaml(path))
