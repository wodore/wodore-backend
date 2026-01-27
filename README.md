<h3 align="center"><b>Wodore Backend</b></h3>
<p align="center">
  <a href="https://wodo.re"><img src="https://wodore.com/icons/icon-192x192.png?v=3" alt="Wodore Backend" width="100" /></a>
</p>
<p align="center">
    <em><b><a href="https://wodo.re" style="color: inherit; text-decoration: none;">wodo.re</a></b> backend implementation</em>
</p>
<p align="center">
    <b><a href="https://wodo.re">wodo.re</a></b>
    &#9679; <b><a href="https://api.wodore.com/">api.wodore.com</a></b> </br>
    <small><a href="https://github.com/wodore/wodore-backend/pkgs/container/wodore-backend">docker images</a>
    &ndash; <a href="https://wodore.github.io/wodore-backend/">documentation</a></small>
</p><p>&nbsp;</p>

## Used Stack

#### Production

- [Django](https://www.djangoproject.com/) with [django ninja](https://django-ninja.dev/) for the API and [unfold admin](https://unfoldadmin.com/)
- [PostgreSQL](https://www.postgresql.org/) with [PostGIS](https://postgis.net/) for the database
- [Martin](https://maplibre.org/martin/) for vector tile serving
- [Imagor](https://github.com/cshum/imagor) for image serving and processing
- [Zitadel](https://zitadel.com/) for authentication and user management _(optional)_

#### Dev Tools

- [uv](https://docs.astral.sh/uv/) for package management
- [infisical](https://infisical.com/) for secrets management _(optional)_

## Development

### Initial Setup

Check [Prerequisites](#prerequisites) for required tools.

When first cloning the repository:

```bash
# Install Python packages and set up virtualenv
make init
# or
uv sync
uv run invoke install
# afterwards activate the virtual environment
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

### Required PostgreSQL Extensions

The application requires the following PostgreSQL extensions for full functionality:

- **`postgis`** - Geographic objects and spatial queries (already included in PostGIS image)
- **`pg_trgm`** - Trigram similarity for fuzzy search and typo tolerance
- **`unaccent`** - Accent-insensitive text search (optional but recommended)

These extensions are installed automatically via Django migrations when you run `app migrate`. If you need to install them manually (e.g., on a production database):

```bash
# Development (Docker)
docker compose exec db psql -U wodore -d wodore -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
docker compose exec db psql -U wodore -d wodore -c "CREATE EXTENSION IF NOT EXISTS unaccent;"

# Production/Kubernetes
kubectl exec wd-backend-postgres-1 -- psql -U postgres -d wodore -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
kubectl exec wd-backend-postgres-1 -- psql -U postgres -d wodore -c "CREATE EXTENSION IF NOT EXISTS unaccent;"

# Or via any PostgreSQL client
psql -U wodore -d wodore -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
psql -U wodore -d wodore -c "CREATE EXTENSION IF NOT EXISTS unaccent;"
```

**Note:** Most managed PostgreSQL services (AWS RDS, Google Cloud SQL, Azure Database) allow these extensions without superuser privileges. If you encounter permission errors, contact your database administrator.

## Start Application

Start the application using the app alias (recommended):

```bash
(.venv) app migrate
(.venv) app run -p 8000 # -i # with infisical
```

Or use invoke with infisical:

```bash
(.venv) app migrate -i
(.venv) app run -p 8000 -i
(.venv) # or written out
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
npx tailwindcss -i styles.css -o server/apps/manager/static/css/styles.css --minify --watch
```

Sync Martin tile server assets for production (Kubernetes):

```bash
# Preview sync (dry-run) - syncs all categories by default
(.venv) app martin_sync --dry-run

# Sync to default target (./martin_sync)
(.venv) app martin_sync

# Sync specific categories only
(.venv) app martin_sync --include accommodation,transport

# Sync to custom target (e.g., production PVC)
(.venv) app martin_sync --target /mnt/martin-pvc
```

### Package Updates

Update all packages:

```bash
(.venv) inv update # OR
(.venv) inv update --no-private # do not update private packages (this removes the private packages)

# Update hut-service (private package only)
(.venv) inv update -p hut-services-private
(.venv) # uv sync --upgrade-package hut-services-private --extra private
(.venv) # uv lock
```

### Changes

After changes the version in `pyproject.toml` needs to be updated and the `wodore-backend` package updated and the docker image published:

```bash
(.venv) vim pyproject.toml
(.venv) inv update -p wodore-backend
(.venv) # uv sync --upgrade-package wodore-backend --extra private
(.venv) inv docker.build --push # --version-tag
```

### Release

For a release run `inv release`.
Merge this change into the `main` branch, the github action will create a tag and a release.

## Docker Production Build

Set required environment variables (or add it to the `.env` file):

```bash
READ_GITHUB_USER=<username>
READ_GITHUB_TOKEN=<token>  # Must have read access
```

(run `infisical export --env dev --path /keys/wodore-backend` to export the secrets)

Build and run Docker images (default is alpine image):

```bash
# Build main image
(.venv) inv docker.build [--distro alpine|ubuntu] [-p/--push] [-v/--version-tag]

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
- `infisical` ([installation guide](https://infisical.com/docs/cli/overview#installation)) (optional)
- `uv` ([installation guide](https://docs.astral.sh/uv/getting-started/installation/))
- `node` and `npm` for Tailwind CSS
- `make` (optional)

## TODOs

See [TODOS.md](TODOS.md) for future improvements and refactoring ideas.
