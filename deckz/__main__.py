from argparse import ArgumentParser
from logging import getLogger, INFO
from sys import exit

from coloredlogs import install as coloredlogs_install

from deckz.cli import commands
from deckz.exceptions import DeckzException


def main() -> None:
    coloredlogs_install(
        level=INFO, fmt="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S",
    )
    logger = getLogger(__name__)
    try:
        parser = ArgumentParser()
        subparsers = parser.add_subparsers(title="Commands")
        for command in commands:
            subparser = subparsers.add_parser(
                name=command.name, help=command.description
            )
            subparser.set_defaults(handler=command.handler)
            command.parser_definer(subparser)
        args = parser.parse_args()
        if not hasattr(args, "handler"):
            parser.print_help()
            exit(1)
        handler = args.handler
        delattr(args, "handler")
        handler(**vars(args))
    except DeckzException as e:
        logger.critical(str(e))
        exit(1)


if __name__ == "__main__":
    main()
