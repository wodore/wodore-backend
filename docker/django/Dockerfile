# syntax = docker/dockerfile:1
# This Dockerfile uses multi-stage build to customize DEV and PROD images:
# https://docs.docker.com/develop/develop-images/multistage-build/

################################################################################
## PYTHON BASE
FROM ghcr.io/osgeo/gdal:alpine-small-latest AS python-base

LABEL maintainer="wodore.com"
LABEL vendor="wodore.com"

# `DJANGO_ENV` arg is used to make prod / dev builds:
ARG DJANGO_ENV \
  # Needed for fixing permissions of files created by Docker:
  UID=1000 \
  GID=1000 \
  CONFIG_DIR="config" \
  WITH_DEV=0

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
  # poetry:
  POETRY_VERSION=1.8.3 \
  POETRY_NO_INTERACTION=1 \
  POETRY_VIRTUALENVS_IN_PROJECT=1 \
  POETRY_VIRTUALENVS_CREATE=1 \
  POETRY_CACHE_DIR='/var/cache/pypoetry' \
  POETRY_HOME='/usr/local'

#SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

WORKDIR /code

#RUN --mount=type=ssh bundle install

# RUN apk add --no-cache \
#     bash 
# 


# System deps (we don't use exact versions because it is hard to update them,
# pin when needed):
# hadolint ignore=DL3008
RUN apk update && \
    apk upgrade && \
    apk add --no-cache \
    bash \
    python3=~3.12 \
    # add user and group
    && addgroup -g "${GID}"  web \
    && adduser -h '/code' -G web -D -u "${UID}" --no-create-home web

################################################################################
## BUILDER
FROM python-base AS builder

    #build-essential \

# System deps (we don't use exact versions because it is hard to update them,
# pin when needed):
# hadolint ignore=DL3008
RUN apk update && \
    apk upgrade && \
    apk add --no-cache \
    build-base \
    git \
    openssh-client \
    libpq-dev \
    poetry=~${POETRY_VERSION} \
  # Installing `poetry` package manager:
  # https://github.com/python-poetry/poetry
  # && curl -sSL 'https://install.python-poetry.org' | python - \
  && poetry --version

#&& ssh-keyscan github.com >> ~/.ssh/known_hosts
#RUN echo "Host remotehost\n\tStrictHostKeyChecking no\n" >> /root/.ssh/config

## RUN mkdir -p -m 0700 /root/.ssh #&& cat /run/secrets/ssh_id_ed25519 > /root/.ssh/id_ed25519 && chmod 600 /root/.ssh/id_25519
## RUN --mount=type=secret,id=ssh_id_ed25519,required cat /run/secrets/ssh_id_ed25519 > /root/.ssh/id_ed25519 && chmod 600 /root/.ssh/id_ed25519

##RUN printf "Host * \n\tStrictHostKeyChecking no\n" >> /root/.ssh/config

# Download public key for github.com
RUN mkdir -p -m 0600 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts


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
COPY --chown=web:web ./poetry.lock ./pyproject.toml ./docker/django/remove_locale.sh /code/
#COPY --chown=web:web  /code/remove_locale.sh

# Project initialization:
# hadolint ignore=SC2046
RUN --mount=type=cache,target="$POETRY_CACHE_DIR" --mount=type=ssh  \
  echo "$DJANGO_ENV" \
  && poetry version \
  # Install deps:
  && poetry run pip install -U pip \
  && poetry install \
   $(if [ "$WITH_DEV" = '0' ]; then echo '--only main'; fi) \
    --no-root --no-interaction --no-ansi --sync --extras private

RUN chmod +x ./remove_locale.sh  \
  && ./remove_locale.sh

################################################################################
## PRODUCTION
FROM python-base AS production

ADD --chown=web:web https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh /usr/local/bin/wait-for-it
# this packages are required by geodjango
# System deps (we don't use exact versions because it is hard to update them,
# pin when needed):
# hadolint ignore=DL3008
RUN apk update && \
    apk upgrade && \
    apk add --no-cache \
    postgresql-client \
    geos \
    brotli \
    gettext \
    tini \
    tzdata \
    && cp /usr/share/zoneinfo/Europe/Zurich /etc/localtime \
    && echo "Europe/Zurich" > /etc/timezone \
    && chmod +x /usr/local/bin/wait-for-it

ENV VIRTUAL_ENV=/code/.venv \
    PATH="/code/.venv/bin:$PATH" \
    TZ="Europe/Zurich"

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

# This is a special case. We need to run this script as an entry point:
COPY ./docker/django/entrypoint.sh /docker-entrypoint.sh


WORKDIR /code
COPY --chown=web:web ./manage.py /code/
COPY --chown=web:web server /code/server
# TODO: collectstatic in build process and copy from there!
#COPY --chown=web:web static /code/static 
COPY --chown=web:web ${CONFIG_DIR} /code/config

# Setting up proper permissions:
RUN chmod +x '/docker-entrypoint.sh' \
  && python manage.py collectstatic --noinput

# Running as non-root user:
# TODO
USER web

#ENTRYPOINT ["sleep", "3600"] # use "docker compose exec web sh" to connect

# We customize how our app is loaded with the custom entrypoint:
ENTRYPOINT ["tini", "--", "/docker-entrypoint.sh"]


# The following stage is only for production:
# https://wemake-django-template.readthedocs.io/en/latest/pages/template/production.html
#FROM development_build AS production_build
