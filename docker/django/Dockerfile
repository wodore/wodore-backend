# syntax = docker/dockerfile:1
# This Dockerfile uses multi-stage build to customize DEV and PROD images:
# https://docs.docker.com/develop/develop-images/multistage-build/

FROM python:3.11.5-slim-bookworm AS python-base

LABEL maintainer="wodore.com"
LABEL vendor="wodore.com"

# `DJANGO_ENV` arg is used to make prod / dev builds:
ARG DJANGO_ENV \
  # Needed for fixing permissions of files created by Docker:
  UID=1000 \
  GID=1000 \
  CONFIG_DIR="config"

ENV DJANGO_ENV=${DJANGO_ENV} \
  # python:
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PYTHONDONTWRITEBYTECODE=1 \
  # pip:
  PIP_NO_CACHE_DIR=1 \
  PIP_DISABLE_PIP_VERSION_CHECK=1 \
  PIP_DEFAULT_TIMEOUT=100 \
  PIP_ROOT_USER_ACTION=ignore \
  # tini:
  TINI_VERSION=v0.19.0 \
  # poetry:
  POETRY_VERSION=1.8.2 \
  POETRY_NO_INTERACTION=1 \
  POETRY_VIRTUALENVS_IN_PROJECT=1 \
  POETRY_VIRTUALENVS_CREATE=1 \
  POETRY_CACHE_DIR='/var/cache/pypoetry' \
  POETRY_HOME='/usr/local'

SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

WORKDIR /code

#RUN --mount=type=ssh bundle install

RUN groupadd -g "${GID}" -r web \
  && useradd -d '/code' -g web -l -r -u "${UID}" web

# System deps (we don't use exact versions because it is hard to update them,
# pin when needed):
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y \
  && apt-get install --no-install-recommends -y \
    brotli \
    gettext \
    wait-for-it \
    libproj-dev \
    gdal-bin

## BUILDER
FROM python-base as builder-base

# System deps (we don't use exact versions because it is hard to update them,
# pin when needed):
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y \
  && apt-get install --no-install-recommends -y \
    bash \
    brotli \
    build-essential \
    curl \
    gettext \
    git \
    openssh-client \
    libpq-dev \
    wait-for-it \
    binutils \
    libproj-dev \
    gdal-bin \
  # Installing `tini` utility:
  # https://github.com/krallin/tini
  # Get architecture to download appropriate tini release:
  # See https://github.com/wemake-services/wemake-django-template/issues/1725
  && dpkgArch="$(dpkg --print-architecture | awk -F- '{ print $NF }')" \
  && curl -o /usr/local/bin/tini -sSLO "https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini-${dpkgArch}" \
  && chmod +x /usr/local/bin/tini && tini --version \
  # Installing `poetry` package manager:
  # https://github.com/python-poetry/poetry
  && curl -sSL 'https://install.python-poetry.org' | python - \
  && poetry --version \
  # Cleaning cache:
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && apt-get clean -y && rm -rf /var/lib/apt/lists/*

#&& ssh-keyscan github.com >> ~/.ssh/known_hosts
#RUN echo "Host remotehost\n\tStrictHostKeyChecking no\n" >> /root/.ssh/config

RUN mkdir -p -m 0700 /root/.ssh #&& cat /run/secrets/ssh_id_ed25519 > /root/.ssh/id_ed25519 && chmod 600 /root/.ssh/id_25519
RUN --mount=type=secret,id=ssh_id_ed25519,required cat /run/secrets/ssh_id_ed25519 > /root/.ssh/id_ed25519 && chmod 600 /root/.ssh/id_ed25519
#RUN cat /run/secrets/ssh_id_ed25519 > /root/.ssh/id_ed25519 && chmod 600 /root/.ssh/id_25519
RUN printf "Host * \n\tStrictHostKeyChecking no\n" >> /root/.ssh/config


WORKDIR /code

#RUN --mount=type=ssh bundle install

#RUN groupadd -g "${GID}" -r web \
  #&& useradd -d '/code' -g web -l -r -u "${UID}" web \
RUN chown web:web -R '/code' \
  # Static and media files:
  && mkdir -p '/var/www/django/static' '/var/www/django/media' \
  #&& mkdir -p '/var/www/django/ssh'  \
  #&& mkdir -p '/.ssh' '/ssh' \
  && chown web:web '/var/www/django/static' '/var/www/django/media'

# Copy only requirements, to cache them in docker layer
COPY --chown=web:web ./poetry.lock ./pyproject.toml /code/

# Project initialization:
# hadolint ignore=SC2046
RUN --mount=type=cache,target="$POETRY_CACHE_DIR" \
  echo "$DJANGO_ENV" \
  && poetry version \
  # Install deps:
  && poetry run pip install -U pip \
  && poetry install \
    $(if [ "$DJANGO_ENV" = 'production' ]; then echo '--only main'; fi) \
    --no-interaction --no-ansi --sync --extras private
    
FROM python-base as production

ENV VIRTUAL_ENV=/code/.venv \
    PATH="/code/.venv/bin:$PATH"
COPY --from=builder-base ${VIRTUAL_ENV} ${VIRTUAL_ENV}
COPY --from=builder-base "/usr/local/bin/tini" "/usr/local/bin/tini"

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    curl

# This is a special case. We need to run this script as an entry point:
COPY ./docker/django/entrypoint.sh /docker-entrypoint.sh

# Setting up proper permissions:
RUN chmod +x '/docker-entrypoint.sh' \
  # Replacing line separator CRLF with LF for Windows users:
  && sed -i 's/\r$//g' '/docker-entrypoint.sh'

WORKDIR /code
COPY --chown=web:web ./manage.py /code/
COPY --chown=web:web server /code/server
# TODO: collectstatic in build process and copy from there!
COPY --chown=web:web static /code/static 
COPY --chown=web:web ${CONFIG_DIR} /code/config

# Running as non-root user:
# TODO
USER web

#ENTRYPOINT ["sleep", "3600"] # use "docker compose exec web sh" to connect

# We customize how our app is loaded with the custom entrypoint:
ENTRYPOINT ["tini", "--", "/docker-entrypoint.sh"]


# The following stage is only for production:
# https://wemake-django-template.readthedocs.io/en/latest/pages/template/production.html
#FROM development_build AS production_build
