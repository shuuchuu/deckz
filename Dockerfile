FROM python:3.14-slim-trixie

ARG DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt update \
  && apt install -y --no-install-recommends \
  curl \
  git \
  gpg \
  make \
  pandoc \
  && apt-get autoremove --purge -y \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/bin/bash"]
