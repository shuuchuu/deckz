#  To make this function accessible from the command line in the current shell,
# dot source them using the following command:
# . .\Makefile.ps1

function check {
    ruff check src/deckz tests
    mypy src/deckz tests
}
function build-and-push-docker-image {
    docker build -t shuuchuu/deckz-ci .
    docker push shuuchuu/deckz-ci:latest
}

function make {
    check
    build-and-push-docker-image
}

