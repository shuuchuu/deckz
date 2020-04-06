check:
	black --check deckz
	mypy deckz
	flake8 --count deckz
	pylint deckz
