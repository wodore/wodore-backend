# wodore

## First time setup
```bash
cp config/.env.template config/.env
ln -s config/.env .env
```

## Start Database and Image Service

This is needed once after each restart of the computer

```bash
docker compose up --build -d
uv sync
source .venv/bin/activate
```

Secrets are managed with [infisical](https://infisical.com/).
For this the `infisical` cli needs to be [installed](https://infisical.com/docs/cli/overview#installation).

After the installation it needs to be initialized.


```bash
infisical login
infisical init

# use infisical run alias for 'app' command
echo 'alias app="infisical run --env=dev --path /backend --silent --log-level warn -- app "' >> .venv/bin/activate
# or export .env file into config folder (this needs to be done everytime a secret changes).
infisical export --env dev --path /backend >> config/.env
```

Get image sizes:

```bash
docker images | grep wodore-backend
```

## Start Application
```bash
(.venv) app migrate
(.venv) app runserver
```


```bash
(.venv) app migrate
(.venv) app loaddata --app huts organizations
```

```bash
(.venv) app squashmigrations huts 0006 --squashed-name init
```

```bash
npx tailwindcss -o server/apps/admin/static/css/styles.css --minify --watch
```

### Update packages
```bash
uv sync --extra private -U
```

#### Update hut-service
```bash
# this is not supported at the moment, update is done with the private package
# uv sync --upgrade-package hut-services
uv sync --upgrade-package hut-services-private --extra private
```

## Docker Production Build

```bash
infisical export --env dev --path /keys/wodore-backend >> .env
# this env variables are needed:
# READ_GITHUB_USER
# READ_GITHUB_TOKEN # with read access
inv docker.build --distro alpine|ubuntu
inv docker.slim --distro alpine|ubuntu # create a slim version
inv docker.run --distro alpine|ubuntu [--slim]
```


**Deprecated:**

```bash
infisical export --env dev --path /backend >> config/.env #TODO should be removed in future
# staging dev env (not the real production env yet), change --env to prod ...
infisical run --env=dev --path /backend -- docker compose -f docker-compose.yml -f docker/docker-compose.stage.yml build web
```

Wodore Backend

This project was generated with [`wemake-django-template`](https://github.com/wemake-services/wemake-django-template). Current template version is: [351114a377e47417817c4c27a1362e708cf7ed59](https://github.com/wemake-services/wemake-django-template/tree/351114a377e47417817c4c27a1362e708cf7ed59). See what is [updated](https://github.com/wemake-services/wemake-django-template/compare/351114a377e47417817c4c27a1362e708cf7ed59...master) since then.


[![wemake.services](https://img.shields.io/badge/%20-wemake.services-green.svg?label=%20&logo=data%3Aimage%2Fpng%3Bbase64%2CiVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAAABGdBTUEAALGPC%2FxhBQAAAAFzUkdCAK7OHOkAAAAbUExURQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP%2F%2F%2F5TvxDIAAAAIdFJOUwAjRA8xXANAL%2Bv0SAAAADNJREFUGNNjYCAIOJjRBdBFWMkVQeGzcHAwksJnAPPZGOGAASzPzAEHEGVsLExQwE7YswCb7AFZSF3bbAAAAABJRU5ErkJggg%3D%3D)](https://wemake-services.github.io)
[![wemake-python-styleguide](https://img.shields.io/badge/style-wemake-000000.svg)](https://github.com/wemake-services/wemake-python-styleguide)


## Prerequisites

You will need:

- `python3.10` (see `pyproject.toml` for full version)
- `postgresql` with version `13`
- `docker` with [version at least](https://docs.docker.com/compose/compose-file/#compose-and-docker-compatibility-matrix) `18.02`


## Development

When developing locally, we use:

- [`editorconfig`](http://editorconfig.org/) plugin (**required**)
- [`uv`](https://github.com/astral-sh/uv) (**required**)
- [`pyenv`](https://github.com/pyenv/pyenv)
- `pycharm 2017+` or `vscode`


## Documentation

Full documentation is available here: [`docs/`](docs).
