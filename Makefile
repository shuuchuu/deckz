check:
	ruff check deckz tests
	mypy deckz tests

build-and-push-docker-image:
	docker build -t shuuchuu/deckz-ci .
	docker push shuuchuu/deckz-ci:latest

.PHONY: check build-and-push-docker-image
