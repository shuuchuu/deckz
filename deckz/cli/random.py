from logging import getLogger
from pathlib import Path
from random import randint
from typing import Optional

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from yaml import safe_load as yaml_safe_load

from deckz.cli import app
from deckz.exceptions import DeckzException
from deckz.paths import GlobalPaths


@app.command()
def random(
    inclusive_end: int,
    inclusive_start: Optional[int] = 1,
    current_dir: Path = Path("."),
) -> None:
    """Roll the dice and email the result."""
    logger = getLogger(__name__)
    paths = GlobalPaths.from_defaults(current_dir)
    config = yaml_safe_load(paths.mails.read_text(encoding="utf8"))
    if not {"api_key", "mail", "to"}.issubset(config):
        raise DeckzException(
            "api_key, mail or to are not present in the mails.yml config."
        )
    api_key, mail, to = config["api_key"], config["mail"], config["to"]
    result = randint(inclusive_start, inclusive_end)
    logger.info(
        f"I've drawn {result} randomly from {inclusive_start} to {inclusive_end}"
    )
    sendgrid_email = Mail(
        from_email=mail,
        to_emails=to,
        subject=f"deckz random from {inclusive_start} to {inclusive_end}: {result}",
        plain_text_content="Hope you got lucky :)",
    )
    client = SendGridAPIClient(api_key)
    client.send(sendgrid_email)
