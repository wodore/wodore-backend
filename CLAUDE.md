# Claude Development Guide

Quick reference for Claude when working on wodore-backend.

**Note**: This file should be updated whenever important development information, patterns, or infrastructure details are discovered during work on the project.

## Related Projects

The Wodore ecosystem consists of multiple repositories:

- **Backend** (this repository): `wodore-backend/`
- **Frontend**: `../wodore-frontend-quasar/` - Quasar/Vue.js frontend application
- **Hut Services (Public)**: `../hut-services/` - Public library for hut information schemas and base services
- **Hut Services (Private)**: `../hut-services-private/` - Private implementations for external booking services (HRS, SAC, etc.)

All paths are relative to the repository root (`wodore-backend/`).

**Important:**

- **Always check `pyproject.toml` (around lines 134-137)** to see how packages are installed:
  - **Editable mode** (`editable = true`, local `path`): Changes are immediately active, no reinstall needed
  - **Git mode** (`git = "..."`): Changes to local copy won't affect backend until switched to editable mode
- After changing dependencies in `pyproject.toml`, run: `inv update` (not `uv sync` directly)

## Essential Commands

Use `app` command with activated virtualenv (sets environment with infisical):

```bash
# Activate virtualenv first
source .venv/bin/activate

# Django commands (app alias uses infisical for environment)
app <command>

# Examples
app makemigrations
app migrate
app update_availability --all

# Note: app expands to: infisical run --env=dev --path /backend --silent --log-level warn -- app <command>
```

## Project Structure

- **Django Apps**: `server/apps/` (e.g., `huts/`, `availbility/`, `organizations/`)
- **Settings**: `server/settings/components/` (modular settings files)
- **API**: Django Ninja (not DRF) - endpoints typically in `api.py`
- **Admin**: Django Unfold - configuration in `server/settings/components/unfold.py`

## API Documentation

OpenAPI schema available at:

- **Local**: <http://localhost:8000/v1/openapi.json>
- **Production**: <https://hub.wodore.com> (may not be up-to-date during development)

## Tech Stack

- **Framework**: Django with Django Ninja for API
- **Admin**: Django Unfold (customized admin interface) - [Documentation](https://unfoldadmin.com/docs/)
- **Database**: PostgreSQL with PostGIS
- **Dependencies**: hut-services library for external hut information and booking data
- **Secrets**: Infisical for environment variable management

## Infrastructure

### Docker Compose Services

Services are defined in `docker-compose.yml`:

#### PostgreSQL Database (PostGIS)

```bash
# Service name: db
# Container: django-local-postgis
# Image: postgis/postgis:16-3.4-alpine
# Port: 5432

# Connect to database
docker compose exec db psql -U wodore -d wodore

# Example: Drop tables
docker compose exec db psql -U wodore -d wodore -c "DROP TABLE IF EXISTS tablename CASCADE;"

# Default credentials (can be overridden with env vars)
POSTGRES_USER: wodore
POSTGRES_PASSWORD: wodore
POSTGRES_DB: wodore
```

#### Imagor (Image Processing)

```bash
# Service name: imagor
# Container: django-local-imagor
# Image: shumc/imagor:latest
# Port: 8079 (host network mode)

# Configuration
- Base URL: http://localhost:8079
- Unsafe mode enabled (for testing)
- Auto WebP/ACIF conversion enabled
- Secret key: IMAGOR_KEY from env (default: my_key)

# Volumes
- ./media → /mnt/data/source/media (source images)
- ./media/imagor_data/storage → /mnt/data/storage (cached images)
- ./media/imagor_data/result → /mnt/data/result (processed results)

# URL format: /unsafe/{params}/{path}
# Example: /unsafe/300x200/media/huts/image.jpg
```

**Note**: Use `docker compose` (not `docker-compose`) for all commands.

## Common Patterns

### Models

- Use `TimeStampedModel` from `model_utils` for created/modified fields
- Custom managers in separate `managers.py` files
- Translation support with `gettext_lazy`

### Admin

- Inherit from `server.apps.manager.admin.ModelAdmin` (not Django's)
- Use `@display` decorator from `unfold.decorators` for custom displays
- Add apps to TABS in `server/settings/components/unfold.py` for tabbed navigation

### Managers

- Inherit from `server.core.managers.BaseManager`
- Define custom querysets for complex queries

## Current Work: Availability Tracking

The `availbility` app tracks hut booking availability:

- **HutAvailability**: Current state (one row per hut per date)
- **HutAvailabilityHistory**: Change log (append-only)
- **Command**: `update_availability` - fetches data from external sources
- **Admin**: Added to Huts section as tabs in Unfold
