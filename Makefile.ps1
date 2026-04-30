#  To make this function accessible from the command line in the current shell,
# dot source them using the following command:
# . .\Makefile.ps1

function check {
    ruff check src/deckz tests
	ruff format --check src/deckz tests
    ty check src/deckz tests
}

function test {
    pytest
}

function build-and-push-docker-image {
    docker build -t shuuchuu/deckz-ci .
    docker push shuuchuu/deckz-ci:latest
}

function make {
    check
    test
    build-and-push-docker-image
}

