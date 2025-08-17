from pathlib import Path

from .. import app


@app.command()
def random(
    reason: str,
    /,
    *,
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Roll the dice and email the result.

    The given REASON will be used as email object ("Pay the bill").

    Args:
        reason: Reason to mention in the email for rolling the dice
        dry_run: Roll the dice and display the result without sending any email
        workdir: Path to move into before running the command

    Raises:
        ValueError: If the number given during recipients selection are not between 0 \
            and n - 1 where n is the number of possible recipients

    """
    from logging import getLogger
    from random import choice

    from rich.console import Console
    from rich.markdown import Markdown
    from rich.prompt import Prompt
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    from ...configuring.settings import GlobalSettings
    from ...extras.mailing import MailsConfig

    logger = getLogger(__name__)
    config = MailsConfig.from_yaml(GlobalSettings.from_yaml(workdir).paths.mails)
    console = Console()
    names = list(config.to)
    names_list_str = "\n".join(
        f"{i}. {name} <{config.to[name]}>" for i, name in enumerate(names, start=1)
    )
    console.print(Markdown(f"Here are the possible participants:\n\n{names_list_str}"))
    print()
    ok = False
    default = ", ".join(map(str, range(1, len(names) + 1)))
    while not ok:
        answer = Prompt().ask(
            "Please enter a comma separated list of numbers to select participants "
            f"(default: {default})",
            default=default,
        )
        numbers_str = answer.split(",")
        try:
            numbers = [int(number_str.strip()) for number_str in numbers_str]
            if not all(0 < n <= len(names) for n in numbers):
                msg = "all numbers should be between 1 and the number of participants"
                raise ValueError(msg)
            ok = True
        except Exception:
            console.print("Could not parse your selection, please try again.")
    selected_names = [names[i - 1] for i in numbers]
    name = choice(selected_names)
    draw_info = f"{name} was drawn randomly from {', '.join(selected_names)}"
    logger.info(draw_info)
    if not dry_run:
        sendgrid_email = Mail(
            from_email=config.mail,
            to_emails=list(config.to.values()),
            subject=f"[deckz random] {reason}: {name} got picked",
            plain_text_content=draw_info,
        )
        client = SendGridAPIClient(config.api_key)
        client.send(sendgrid_email)
