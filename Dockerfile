FROM python:3.9.4-slim-buster

ARG DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt update \
  && apt install -y --no-install-recommends \
  curl \
  latexmk \
  make \
  texlive \
  texlive-lang-english \
  texlive-lang-french \
  texlive-science \
  texlive-xetex \
  && apt-get remove -y .*-doc .*-man >/dev/null \
  && apt-get autoremove --purge -y \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/* \
  && curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/install-poetry.py | python - \
  && ln -s /root/.local/bin/poetry /usr/bin

ENTRYPOINT ["/bin/bash"]
