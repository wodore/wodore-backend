<h3 align="center"><b>Wodore Backend</b></h3>
<p align="center">
  <a href="https://wodore.com"><img src="https://avatars.githubusercontent.com/u/12153020?s=200&v=4" alt="Wodore Backend" width="60" /></a>
</p>
<p align="center">
    <em>Wodore.com backend implementation</em>
</p>
<p align="center">
    <b><a href="https://wodore.com">wodore.com</a></b>
    | <b><a href="https://api.wodore.com/">api.wodore.com</a></b>
    | <b><a href="https://github.com/wodore/wodore-backend/pkgs/container/wodore-backend">docker images</a></b>
</p>

----

## Development

### Initial Setup

When first cloning the repository:
```bash
# Install Python packages and set up virtualenv
make init
source .venv/bin/activate
```

### Setup

Activate the virtual environment and install packages:
```bash
source .venv/bin/activate

# With infisical (recommended) -> see Secrets section
(.venv) inv install --infisical

# Without infisical
(.venv) inv install

# View available commands
(.venv) inv help

# Apply changes
source deactivate; source .venv/bin/activate
```

**NOTE:** The install command creates `.volumes/pgdata/` for PostgreSQL data and `media/imagor_data/` for image processing.

### Secrets

Secrets are managed with [infisical](https://infisical.com/). Install the CLI tool following the [installation guide](https://infisical.com/docs/cli/overview#installation) and initialize it:
```bash
infisical login
infisical init
```

Set up secrets using infisical (recommended):
```bash
(.venv) inv install --infisical
source .venv/bin/activate
(.venv) app <cmd> # uses infisical
```

Or use local env files:
```bash
# Export secrets to config/.env (update when secrets change)
infisical export --env dev --path /backend >> config/.env
ln -s config/.env .env
```

Or set up manually:
```bash
# Create and edit env files manually
cp config/.env.template config/.env
ln -s config/.env .env
# edit .env
```

**TIP:** Add `-i/--infisical` to `inv` commands (e.g., `run`, `docker-compose`) to use infisical directly.

### Start Database and Image Service

Start PostgreSQL and Imagor services after each system restart:
```bash
# With infisical (recommended)
(.venv) inv docker-compose -c "up -d" -i

# Without infisical (requires .env file)
(.venv) inv docker-compose -c "up -d"
```

**NOTE:** PostgreSQL data is stored in `.volumes/pgdata/` (development only). To reset the database:
```bash
rm -rf .volumes/pgdata/*  # Be careful!
(.venv) inv docker-compose -c "up -d"
```


## Start Application

Start the application using the app alias (recommended):
```bash
(.venv) app migrate
(.venv) app runserver
```

Or use invoke with infisical:
```bash
(.venv) inv app.app -i --cmd "migrate"
(.venv) inv app.app -i --cmd "runserver"
```

Or use local env files (requires `.env` and `config/.env`):
```bash
(.venv) inv app.app --cmd "migrate"
(.venv) inv app.app --cmd "runserver"
```

**NOTE:** The `app` command expands to if infisical is used:
```bash
infisical run --env=dev --path /backend --silent --log-level warn -- app <command>
```

## Load Data

Copy hut information from sources, this saves huts information from
different sources (e.g. refuges.info, wikidata, open stree map) into the
local database
```bash
# Add all available sources
(.venv) app hut_sources --add --orgs all

# Add specific source (e.g. refuges)
(.venv) app hut_sources --add --orgs refuges
```
Add huts from the previously added sources.
If a hut has multiple sources they are combined as good as possible.

```bash
# Add huts from sources (combines data if multiple sources)
(.venv) app huts --add-all
```

## Helpful Commands

Common database commands:
```bash
# Apply migrations
(.venv) app migrate

# Load initial data
(.venv) app loaddata --app huts organizations

# Squash migrations
(.venv) app squashmigrations huts 0006 --squashed-name init
```

Watch and compile Tailwind CSS:
```bash
npx tailwindcss -i styles.css -o server/apps/admin/static/css/styles.css --minify --watch
```

### Package Updates

Update all packages:
```bash
inv update # OR
inv update --no-private # do not update private packages

# Update hut-service (private package only)
uv sync --upgrade-package hut-services-private --extra private

# uv lock
```

## Docker Production Build

Set required environment variables (or add it to the `.env` file):
```bash
READ_GITHUB_USER=<username>
READ_GITHUB_TOKEN=<token>  # Must have read access
```

Build and run Docker images (default is alpine image):
```bash
# Build main image
(.venv) inv docker.build [--distro alpine|ubuntu]

# Create slim version (optional)
(.venv) inv docker.slim [--distro alpine|ubuntu]

# Run the container
(.venv) inv docker.run [--distro alpine|ubuntu] [--slim]

# Publish the container (use -v to include version tags as well, otherwise only 'edge' is pushed)
(.venv) inv docker.publish [--distro alpine|ubuntu] [--slim] [-v/--version-tag]
```

**NOTE:** These commands are deprecated:
```bash
# Export secrets (will be removed)
infisical export --env dev --path /backend >> config/.env

# Build staging (use --env=prod for production)
infisical run --env=dev --path /backend -- \
  docker compose -f docker-compose.yml \
  -f docker/docker-compose.stage.yml build web
```

## Prerequisites

Required development tools:
- `python3.12` (see `pyproject.toml`)
- `postgresql13`
- `docker` with `docker compose`
- `infisical` ([installation guide](https://infisical.com/docs/cli/overview#installation))
- `poetry` ([installation guide](https://python-poetry.org/docs/#installation))
- `node` and `npm` for Tailwind CSS
- `make` (optional)
