# Claude Development Guide

Quick reference for Claude when working on wodore-backend.

**Note**: This file should be updated whenever important development information, patterns, or infrastructure details are discovered during work on the project.

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

## Tech Stack

- **Framework**: Django with Django Ninja for API
- **Admin**: Django Unfold (customized admin interface) - [Documentation](https://unfoldadmin.com/docs/)
- **Database**: PostgreSQL with PostGIS
- **Dependencies**: hut-services library for external hut information and booking data
- **Secrets**: Infisical for environment variable management

## Related Projects

The Wodore ecosystem consists of multiple repositories:

- **Backend** (this repository): `wodore-backend/`
- **Frontend**: `../wodore-frontend-quasar/` - Quasar/Vue.js frontend application
- **Hut Services (Public)**: `../hut-services/` - Public library for hut information schemas and base services
- **Hut Services (Private)**: `../hut-services-private/` - Private implementations for external booking services (HRS, SAC, etc.)

All paths are relative to the repository root (`wodore-backend/`).

### WEPs (Wodore Enhancement Proposals)

Technical proposals for significant features and architectural decisions:

- **Location**: `docs/weps/board/` - Blog posts in MkDocs
- **Format**: Single-sentence summary + detailed analysis with categories/tags
- **Build**: `inv docs.serve` - Shows all WEPs with integrated TOC in left sidebar
- **Online Access**: `/weps/` (blog index), `/weps/tags/` (tags), `/weps/category/` (categories)

## Infrastructure

### Docker Compose Services

Services are defined in `docker-compose.yml`:

- PostgreSQL Database (PostGIS)
- Imagor (Image Processing)

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

**Key Points:**

- Use `Query(...)` for required parameters with description (NOT `Field()` - that's for Pydantic schemas)
- Use `Query(default_value, description=...)` for optional parameters
- Add `example="value"` only when it helps clarify usage (e.g., for search strings, special formats, or non-obvious numeric values)
- Skip examples for obvious types like simple integers, booleans, or enums (Swagger UI shows these well)
- `exclude_unset=True` works by not adding fields to the response dict when they shouldn't be included
- Don't set fields to `None` if you want them excluded - simply don't add them to the result dict
- Add detailed descriptions explaining what values mean, especially for numeric thresholds or enum options
