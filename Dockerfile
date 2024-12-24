FROM python:3.12-slim-bullseye

ARG DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt update \
  && apt install -y --no-install-recommends \
  curl \
  git \
  latexmk \
  make \
  texlive \
  texlive-lang-english \
  texlive-lang-french \
  texlive-latex-extra \
  texlive-science \
  texlive-xetex \
  && apt-get autoremove --purge -y \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/bin/bash"]
