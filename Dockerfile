FROM python:3.8.1-slim-buster

WORKDIR /workdir

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    git

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY README.md .
COPY setup.py .
COPY deckz ./deckz

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["deckz"]
