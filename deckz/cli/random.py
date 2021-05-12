from logging import getLogger
from pathlib import Path
from random import randint
from typing import List

from pydantic import BaseModel
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from yaml import safe_load

from deckz.cli import app
from deckz.paths import GlobalPaths


@app.command()
def random(
    inclusive_end: int,
    inclusive_start: int = 1,
    current_dir: Path = Path("."),
) -> None:
    """Roll the dice and email the result."""
    logger = getLogger(__name__)
    config = MailsConfig.from_global_paths(GlobalPaths.from_defaults(current_dir))
    result = randint(inclusive_start, inclusive_end)
    logger.info(
        f"I've drawn {result} randomly from {inclusive_start} to {inclusive_end}"
    )
    sendgrid_email = Mail(
        from_email=config.mail,
        to_emails=config.to,
        subject=f"deckz random from {inclusive_start} to {inclusive_end}: {result}",
        plain_text_content="Hope you got lucky :)",
    )
    client = SendGridAPIClient(config.api_key)
    client.send(sendgrid_email)


class MailsConfig(BaseModel):

    api_key: str
    mail: str
    to: List[str]

    @classmethod
    def from_global_paths(cls, paths: GlobalPaths) -> "MailsConfig":
        return cls.parse_obj(safe_load(paths.mails.read_text(encoding="utf8")))
