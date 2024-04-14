from pydantic import BaseModel, EmailStr
from yaml import safe_load

from .paths import GlobalPaths


class MailsConfig(BaseModel):
    api_key: str
    mail: str
    to: dict[str, EmailStr]

    @classmethod
    def from_global_paths(cls, paths: GlobalPaths) -> "MailsConfig":
        return cls.model_validate(safe_load(paths.mails.read_text(encoding="utf8")))
