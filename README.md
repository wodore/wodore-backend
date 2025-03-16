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

**NOTE:** These steps are only needed when first cloning the repository:
```bash
# Install Python packages and set up virtualenv
make init
source .venv/bin/activate
```

### Setup

Activate the virtual environment and install the needed python packages:

1. Activate virtualenv and install dependencies:
   ```bash
   source .venv/bin/activate

   # With infisical (recommended)
   (.venv) inv install --infisical

   # Without infisical
   (.venv) inv install
   ```

2. View available commands:
   ```bash
   (.venv) inv help
   ```

3. Apply changes:
   ```bash
   source deactivate; source .venv/bin/activate
   ```

**NOTE:** The install command creates these directories:
- `.volumes/pgdata/`: PostgreSQL data
- `media/imagor_data/storage/`: Image storage
- `media/imagor_data/result/`: Image processing results

### Secrets

Secrets are managed with [infisical](https://infisical.com/). First, install the CLI tool:
1. Follow the [installation guide](https://infisical.com/docs/cli/overview#installation)
2. Initialize infisical:
   ```bash
   infisical login
   infisical init
   ```

Set up secrets using one of these methods:

1. Using infisical directly (recommended):
   ```bash
   # Add app alias to virtualenv
   echo 'alias app="infisical run --env=dev --path /backend --silent --log-level warn -- app "' >> .venv/bin/activate
   ```

2. Using local env files:
   ```bash
   # Export secrets to config/.env (update when secrets change)
   infisical export --env dev --path /backend >> config/.env
   ln -s config/.env .env
   ```

3. Manual setup:
   ```bash
   # Create and edit env files manually
   cp config/.env.template config/.env
   ln -s config/.env .env
   ```

**NOTE:** When using `inv` commands (e.g., `run`, `docker-compose`), add `-i/--infisical` to use infisical directly.

### Start Database and Image Service

**NOTE:** Start required services after each system restart:
```bash
# With infisical (recommended)
(.venv) inv docker-compose -c "up -d" -i

# Without infisical (requires .env file)
(.venv) inv docker-compose -c "up -d"
```

This starts PostgreSQL and Imagor services which are required to run the backend locally.

**NOTE:** PostgreSQL data is stored in a local volume at `.volumes/pgdata/` (created during installation). This setup is for development only.

**NOTE:** To reset the database or change credentials:
```bash
rm -rf .volumes/pgdata/*  # Be careful with this command!
(.venv) inv docker-compose -c "up -d"
```

**NOTE:** The `.volumes/` directory is gitignored.


## Start Application

There are three ways to start the application:

1. Using the app alias with infisical (recommended):
   ```bash
   # The alias is added to .venv/bin/activate during install
   (.venv) app migrate
   (.venv) app runserver
   **NOTE:** The `app` alias expands to:
   ```bash
   infisical run --env=dev --path /backend --silent --log-level warn -- app <command>
  ```

2. Using invoke with infisical:
   ```bash
   # Use -i flag for infisical integration
   (.venv) inv app.app -i --cmd "migrate"
   (.venv) inv app.app -i --cmd "runserver"
   ```

3. Using local env files:
   - Requires `.env` and `config/.env` files
   - No infisical integration
   ```bash
   # Use app alias
   (.venv) app migrate
   (.venv) app runserver

   # Or use invoke directly
   (.venv) inv app.app --cmd "migrate"
   (.venv) inv app.app --cmd "runserver"
   ```


This provides convenient access to Django management commands with automatic infisical integration.

## Load Data

Load hut information from various sources (refuges.info, wikidata, OpenStreetMap) into your local database:

1. Add hut sources:
   ```bash
   # Add all available sources
   (.venv) app hut_sources --add --orgs all

   # Add specific source (e.g. refuges)
   (.venv) app hut_sources --add --orgs refuges
   ```

2. Add huts from sources:
   ```bash
   # Add huts from previously added sources
   # If a hut has multiple sources, they are combined
   (.venv) app huts --add-all
   ```

## Helpful Commands

After activating the virtualenv with infisical alias, you can use these common commands:

1. Database Management:
   ```bash
   # Apply migrations
   (.venv) app migrate

   # Load initial data
   (.venv) app loaddata --app huts organizations

   # Squash migrations
   (.venv) app squashmigrations huts 0006 --squashed-name init
   ```

2. Frontend Development:
   ```bash
   # Watch and compile Tailwind CSS
   npx tailwindcss -o server/apps/admin/static/css/styles.css --minify --watch
   ```

### Package Updates

Update all packages including private ones:

```bash
uv sync --extra private -U
```

#### Update hut-service
```bash
# Public package is not supported at the moment
# uv sync --upgrade-package hut-services
uv sync --upgrade-package hut-services-private --extra private
```

## Docker Production Build

Build and run Docker images for production:

1. Required environment variables:
   ```bash
   # Export from infisical or set manually
   READ_GITHUB_USER=<username>
   READ_GITHUB_TOKEN=<token>  # Must have read access
   ```

2. Build commands:
   ```bash
   # Build main image
   (.venv) inv docker.build --distro alpine|ubuntu

   # Create slim version (optional)
   (.venv) inv docker.slim --distro alpine|ubuntu

   # Run the container
   (.venv) inv docker.run --distro alpine|ubuntu [--slim]
   ```

**NOTE:** The following commands are deprecated:
```bash
# Export secrets (will be removed)
infisical export --env dev --path /backend >> config/.env

# Build staging environment (use --env=prod for production)
infisical run --env=dev --path /backend -- \
  docker compose -f docker-compose.yml \
  -f docker/docker-compose.stage.yml build web
```

## Prerequisites

The following tools are required for development:

- `python3.12` (see `pyproject.toml` for full version)
- `postgresql` with version `13`
- `docker` with [version at least](https://docs.docker.com/compose/compose-file/#compose-and-docker-compatibility-matrix) `18.02`
