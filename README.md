<h3 align="center"><b>Wodore Backend</b></h3>
<p align="center">
  <a href="https://wodore.com"><img src="https://avatars.githubusercontent.com/u/12153020?s=200&v=4" alt="Wodore Backend" width="80" /></a>
</p>
<p align="center">
    <em>Wodore.com backend implementation</em>
</p>
<p align="center">
    <b><a href="https://api.wodore.com/">api.wodore.com</a></b>
    | <b><a href="https://github.com/wodore/wodore-backend/pkgs/container/wodore-backend">Docker Images</a></b>
</p>

--

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

## Prerequisites

You will need:

- `python3.12` (see `pyproject.toml` for full version)
- `postgresql` with version `13`
- `docker` with [version at least](https://docs.docker.com/compose/compose-file/#compose-and-docker-compatibility-matrix) `18.02`
