# django-admin-runner updated 0.1.0 → 0.2.0

Date: 2026-09-20

## What was done

Updated the editable install (`/home/tobias/git/burgdev/django-admin-runner`) to the
released **v0.2.0** (tag on `origin/main` @ `d6c1888`, "Release 0.2.0 (#8)").

1. **Package repo**: was on stale `release_0.2.0_fix` (based on pre-#7 main).
   - Uncommitted CI tweaks (`release.yml` curated changelog extraction + `uv.lock`)
     preserved in stash: `stash@{0}` ("release_0.2.0_fix: curated changelog
     extraction..."). These were never merged upstream — rebase onto main and PR
     if still wanted.
   - Checked out `main`, fast-forwarded to `d6c1888` (= tag `v0.2.0`).
   - Note: `origin/release_0.2.0` branch was deleted upstream; local
     `release_0.2.0_fix` branch can be cleaned up once the stash is handled.

2. **wodore-backend**:
   - `uv lock`: django-admin-runner v0.1.0 → v0.2.0 (runtime deps/extras unchanged).
   - `uv sync` (standard, no extras).
   - Applied new migrations `0007_scheduledcommand`, `0008_execution_cancellation`,
     `0009_timeout_status`, `0010_commandexecution_label` to the local dev DB
     (0005/0006 were already applied from a pre-release state).
   - `inv tests`: 8/8 passed.

## What 0.2.0 brings

- xterm.js terminal output (live output, output-delta endpoint), scheduling
  (`ScheduledCommand` + declarative `Schedule`/`CronSchedule`/`IntervalSchedule`/
  `ClockedSchedule`), execution cancellation, timeout status, execution page
  tabs, rerun, `CommandExecution.label`.
- New settings still compatible: `ADMIN_RUNNER_BACKEND = "django-q2"` unchanged.
- New static files (vendored xterm.js) → production deploys need
  `collectstatic` + `migrate`.

## Open items

- ~~**Infisical session expired**~~ — resolved (user logged in again).
- ~~**Package warning** (upstream)~~ — fixed on branch
  `fix/scheduledcommand-source-constraint` in django-admin-runner (commit
  `eb38b22`, rebased onto `origin/main` @ `f7d8238`):
  - `ScheduledCommand.source` CheckConstraint + migration 0011 (+ DB tests)
  - Model state synced with frozen migrations (help_text / label default) —
    removes spurious `AlterField`s from downstream `makemigrations` runs
  - `test_migrations.py::_restore_latest` now migrates to leaf nodes instead
    of hardcoded 0006 (latent ordering flake)
  - `uv.lock` refreshed to 0.2.0
  - Applied 0011 to the wodore dev DB; `manage.py check` fully clean
    (restart `app runserver` to pick it up), `inv tests` 8/8 green.
  - Branch not yet pushed / PR not opened.
  - Note: origin/main gained #9 + #10 (release-notes workflow) during this
    work — the stashed curated-changelog work appears to have landed as #10.
