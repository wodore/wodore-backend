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

## Documentation

### API Documentation

OpenAPI schema available at:

- **Local**: <http://localhost:8000/v1/openapi.json>
- **Production**: <https://hub.wodore.com> (may not be up-to-date during development)

### WEPs (Wodore Enhancement Proposals)

Technical proposals for significant features and architectural decisions:

- **Location**: `docs/weps/board/` - Blog posts in MkDocs
- **Format**: Single-sentence summary + detailed analysis with categories/tags
- **Build**: `inv docs.serve` - Shows all WEPs with integrated TOC in left sidebar
- **Online Access**: `/weps/` (blog index), `/weps/tags/` (tags), `/weps/category/` (categories)

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

## Environment Variables

### Production/Docker Deployment

- **GIT_HASH**: Set this environment variable in production/docker to include git version in ETags for cache busting
  - Example: `GIT_HASH=$(git rev-parse --short HEAD)`
  - If not set, the backend will try to get it from git command (dev only)
  - Falls back to "unknown" if git is unavailable

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

### API Endpoints (Django Ninja)

**Documentation Style:**

- **Function docstring**: Keep it simple, usually one line describing what the endpoint does
- **Parameters**: Use `Query()` from `ninja` to add detailed descriptions for each parameter
- **Examples**: Only add examples if helpful (not for simple integers, bools, or obvious values). Use `example="value"` (singular), not `examples=[...]`
- **Response**: Set `exclude_unset=True` on the router decorator to exclude fields that are not set (avoids null fields in response)

**Example:**

```python
from ninja import Query

@router.get(
    "search",
    response=list[HutSearchResultSchema],
    exclude_unset=True,  # Don't include fields that are not set
    operation_id="search_huts",
)
def search_huts(
    request: HttpRequest,
    response: HttpResponse,
    q: str = Query(
        ...,
        description="Search query string to match against hut names",
        example="Rotondo"
    ),
    limit: int | None = Query(
        15,
        description="Maximum number of results to return"
        # No example needed - it's obvious what an integer limit is
    ),
    threshold: float = Query(
        0.1,
        description="Minimum similarity score (0.0-1.0). Lower values return more results but with lower relevance. Recommended: 0.1 for fuzzy matching, 0.3 for stricter matching.",
        example=0.3
    ),
    include_sources: IncludeModeEnum = Query(
        IncludeModeEnum.no,
        description="Include data sources: 'no' excludes field, 'slug' returns source slugs only, 'all' returns full source details"
        # No example needed - enum values are self-explanatory in Swagger UI
    ),
) -> Any:
    """Search for huts using fuzzy text search across all language fields."""
    # Implementation...
```

**Key Points:**

- Use `Query(...)` for required parameters with description (NOT `Field()` - that's for Pydantic schemas)
- Use `Query(default_value, description=...)` for optional parameters
- Add `example="value"` only when it helps clarify usage (e.g., for search strings, special formats, or non-obvious numeric values)
- Skip examples for obvious types like simple integers, booleans, or enums (Swagger UI shows these well)
- `exclude_unset=True` works by not adding fields to the response dict when they shouldn't be included
- Don't set fields to `None` if you want them excluded - simply don't add them to the result dict
- Add detailed descriptions explaining what values mean, especially for numeric thresholds or enum options

## Current Work: Availability Tracking

The `availbility` app tracks hut booking availability:

- **HutAvailability**: Current state (one row per hut per date)
- **HutAvailabilityHistory**: Change log (append-only)
- **Command**: `update_availability` - fetches data from external sources
- **Admin**: Added to Huts section as tabs in Unfold
