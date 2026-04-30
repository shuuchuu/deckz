check:
	ruff check src/deckz tests
	ruff format --check src/deckz tests
	ty check src/deckz tests

test:
	pytest

build-and-push-docker-image:
	docker build -t shuuchuu/deckz-ci .
	docker push shuuchuu/deckz-ci:latest

.PHONY: check test build-and-push-docker-image
