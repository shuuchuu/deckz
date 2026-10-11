FROM python:3.14-slim-trixie

ARG DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt update \
  && apt install -y --no-install-recommends \
  curl \
  ffmpeg \
  gcc \
  git \
  gpg \
  libcairo2-dev \
  libpango1.0-dev \
  make \
  pandoc \
  pkg-config \
  && apt-get autoremove --purge -y \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/bin/bash"]
