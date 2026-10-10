"""The groups `deckz --help` lists the commands in, by task."""

from cyclopts import Group

EVERYDAY = Group("Everyday", sort_key=0)
NEW = Group("New content", sort_key=1)
CONTENT = Group("Finding content", sort_key=2)
TRANSLATION = Group("Translation", sort_key=3)
LABS_VIDEOS = Group("Labs and videos", sort_key=4)
SETUP = Group("Setting up", sort_key=5)
MAINTENANCE = Group("Repository maintenance", sort_key=6)
