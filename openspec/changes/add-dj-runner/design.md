## Context

The wodore-backend project has 18 management commands spread across 10 apps for data imports, syncs, and maintenance tasks. These commands are currently only runnable via CLI (`app <command>`). The project uses Django Unfold for its admin interface and PostgreSQL/PostGIS for data storage.

The django-admin-runner library provides a `@register_command` decorator that wraps Django management commands, auto-generates admin forms from `add_arguments()`, and tracks execution history. Combined with django-q2 using the ORM backend, this gives us task scheduling and async execution without external infrastructure.

## Goals / Non-Goals

**Goals:**
- Enable running all 18 management commands from the Unfold admin interface
- Provide scheduling capability via django-q2 Schedule model with a command dropdown
- Track command execution history with output capture
- Keep commands fully functional from CLI (decorator is additive)
- Use ORM broker to avoid external dependencies (Redis, etc.)
- Match the Unfold admin styling for django-q2 admin models

**Non-Goals:**
- Replacing existing command arguments or behavior
- Adding Celery or Redis-based task processing
- Creating custom task retry logic beyond django-q2 defaults
- Modifying the command runner UI beyond Unfold defaults
- Running the django-q2 cluster process (that's infrastructure/deployment concern)

## Decisions

### 1. ORM broker for django-q2

**Choice**: Use `Q_CLUSTER` with `orm: "default"` broker.

**Rationale**: Zero additional infrastructure. The project already has PostgreSQL. The ORM broker polls the database for tasks — adequate for the low-frequency management commands in this project. No Redis or other message broker needed.

**Alternative considered**: Redis broker — faster polling but adds an external dependency with no current need for high-throughput task processing.

### 2. Decorator placement — in each command file

**Choice**: Add `@register_command` directly in each management command file.

**Rationale**: Keeps the registration co-located with the command definition. The decorator only adds metadata — it doesn't change command behavior.

### 3. Group naming — use app labels as groups

**Choice**: Use human-readable group names matching the user's specification (Availability, Categories, Computed Fields, etc.).

**Rationale**: Groups organize commands in the admin sidebar. Using readable names matching the app purpose makes navigation intuitive.

### 4. Custom Schedule admin with command dropdown

**Choice**: Unregister django-q2's default admin models and re-register with Unfold-styled versions, including a `func` dropdown populated from the admin runner registry.

**Rationale**: The default django-q2 admin requires manual text entry for `func`. A dropdown listing all registered commands prevents typos and improves UX. Following the django-admin-runner example pattern exactly.

### 5. New admin module for django-q2 models

**Choice**: Create `server/apps/main/admin_django_q.py` (or similar) for the django-q2 admin customizations.

**Rationale**: Keeps the django-q2 admin customization separate from app-specific admin files. The project already has a pattern of admin configuration in settings/components/unfold.py.

## Risks / Trade-offs

- **[ORM broker polling overhead]** → Minimal impact: polling interval is configurable and management commands run infrequently. Acceptable tradeoff for zero external dependencies.
- **[Decorator import side effects]** → The `@register_command` decorator only registers metadata; it doesn't change command execution behavior. Commands remain CLI-compatible.
- **[django-q2 cluster process]** → Needs to be started separately (`app qcluster`). This is a deployment concern, not a code concern. Not addressed in this change.
- **[Database table growth]** → django-q2 Success/Failure tables accumulate over time. Mitigated by django-q2's built-in `save_limit` and `queue_limit` settings, plus periodic cleanup.
