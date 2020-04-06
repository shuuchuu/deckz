FROM python:3.8.1-slim-buster

WORKDIR /workdir

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    curl \
    git \
    && curl -sSL \
    https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py \
    | python

COPY poetry.lock .
COPY pyproject.toml .

RUN /root/.poetry/bin/poetry install --no-root --no-dev

COPY README.md .
COPY deckz ./deckz

RUN /root/.poetry/bin/poetry install --no-dev

ENTRYPOINT ["/root/.poetry/bin/poetry", "run", "deckz"]
