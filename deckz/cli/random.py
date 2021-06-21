from logging import getLogger
from pathlib import Path
from random import choice
from typing import Dict

from pydantic import BaseModel, EmailStr
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from yaml import safe_load

from deckz.cli import app
from deckz.paths import GlobalPaths


@app.command()
def random(
    reason: str,
    current_dir: Path = Path("."),
) -> None:
    """Roll the dice and email the result."""
    logger = getLogger(__name__)
    config = MailsConfig.from_global_paths(GlobalPaths.from_defaults(current_dir))
    names = list(config.to)
    name = choice(names)
    logger.info(f"I've drawn {name} randomly from {', '.join(names)}")
    sendgrid_email = Mail(
        from_email=config.mail,
        to_emails=list(config.to.values()),
        subject=f"[deckz random] {reason}: {name} got picked",
        plain_text_content="See subject :)",
    )
    client = SendGridAPIClient(config.api_key)
    client.send(sendgrid_email)


class MailsConfig(BaseModel):

    api_key: str
    mail: str
    to: Dict[str, EmailStr]

    @classmethod
    def from_global_paths(cls, paths: GlobalPaths) -> "MailsConfig":
        return cls.parse_obj(safe_load(paths.mails.read_text(encoding="utf8")))
