check:
	black --check deckz setup.py
	mypy deckz setup.py
	flake8 --count deckz setup.py
	pylint deckz setup.py

sync:
	@python -c 'import pkgutil; import sys; sys.exit(0 if pkgutil.find_loader("piptools") else 1)' \
		|| echo "Please install pip-tools to use make sync"
	pip-compile setup.py
	pip-compile dev-requirements.in
	pip-sync requirements.txt dev-requirements.txt
