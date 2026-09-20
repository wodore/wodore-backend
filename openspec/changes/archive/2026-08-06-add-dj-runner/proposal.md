## Why

Management commands (imports, syncs, availability updates) currently run only via CLI. There is no way to trigger, schedule, or monitor these commands from the admin interface. Adding django-q2 with the ORM backend and django-admin-runner enables running commands from Unfold admin with scheduling, result tracking, and a polished UI — without introducing external infrastructure like Redis or Celery.

## What Changes

- Add `django-q2` and `django-admin-runner[django-q2,unfold]` as dependencies
- Configure django-q2 with the ORM broker (`Q_CLUSTER` setting)
- Register all management commands with `@register_command` decorator, organized by groups
- Add custom Unfold-styled admin for django-q2 models (Schedule, Success, Failure, OrmQ) with a command dropdown in Schedule
- Update the Unfold sidebar to include Command Runner and Scheduled Tasks navigation
- Add `django_q` and `django_admin_runner` to `INSTALLED_APPS`
- Run migrations for both new packages

## Capabilities

### New Capabilities

- `dj-runner`: Background task runner via django-q2 (ORM backend) with admin command execution via django-admin-runner. Registers all management commands with the `@register_command` decorator, provides Unfold-styled admin for scheduling/monitoring, and integrates into the sidebar navigation.

### Modified Capabilities

## Impact

- **Dependencies**: New packages `django-q2` and `django-admin-runner[django-q2,unfold]` in pyproject.toml
- **Settings**: `INSTALLED_APPS` additions, new `Q_CLUSTER` config, `ADMIN_RUNNER_BACKEND` setting
- **Management commands**: All 18 commands get `@register_command` decorator (non-breaking — commands still work from CLI)
- **Admin**: New admin classes for django-q2 models with Unfold styling; sidebar navigation updates in unfold.py
- **Database**: New migrations for django-q2 and django-admin-runner tables
- **Infrastructure**: No external services needed — ORM broker uses the existing PostgreSQL database
