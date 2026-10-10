"""The groups `deckz --help` lists the commands in, by task."""

from cyclopts import Group

EVERYDAY = Group("Everyday", sort_key=0)
CONTENT = Group("Finding content", sort_key=1)
TRANSLATION = Group("Translation", sort_key=2)
LABS_VIDEOS = Group("Labs and videos", sort_key=3)
SETUP = Group("Setting up", sort_key=4)
MAINTENANCE = Group("Repository maintenance", sort_key=5)
