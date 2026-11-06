## ADDED Requirements

### Requirement: Pyrefly is the project type checker
The project SHALL use pyrefly (pinned exactly in the dev dependency group) as
its only static type checker for Python code, configured via the
`[tool.pyrefly]` section in `pyproject.toml`. No mypy or pyright
configuration or dependency SHALL remain in the repository.

#### Scenario: Type check passes with baseline
- **WHEN** `uv run pyrefly check` runs on the repository
- **THEN** it exits 0, suppressing diagnostics listed in the committed
  baseline file, and reports any type error not present in the baseline

#### Scenario: New type error fails the check
- **WHEN** a code change introduces a type error in a non-excluded file
- **THEN** `pyrefly check` exits non-zero and names the file, line, and rule

### Requirement: django-stubs version tracks the Django major
The dev dependencies SHALL pin `django-stubs` and `django-stubs-ext` to the
major line matching the installed Django version, because pyrefly's Django
ORM inference builds on the stubs' type vocabulary.

#### Scenario: Stubs match Django 6.x
- **WHEN** the project depends on Django 6.x
- **THEN** `django-stubs` and `django-stubs-ext` resolve to `6.*`

### Requirement: Check scope excludes generated code
The pyrefly configuration SHALL include `server/` and `tests/` in checking and
SHALL exclude migration files and dot/cache directories.

#### Scenario: Migrations are not checked
- **WHEN** a type error exists only in a file under `**/migrations/`
- **THEN** `pyrefly check` does not report it

### Requirement: Baseline ratchet gates only new errors
The repository SHALL commit a pyrefly baseline file listing pre-existing
diagnostics. The baseline SHALL only shrink via deliberate regeneration
(`pyrefly check --update-baseline`) as part of error-fixing work, never grow
to absorb newly introduced errors.

#### Scenario: Existing error stays suppressed
- **WHEN** a diagnostic present in the baseline remains in the code
- **THEN** CI type checking passes

#### Scenario: Baseline grows only deliberately
- **WHEN** a pull request adds entries to the baseline file
- **THEN** reviewers treat it as a policy exception requiring justification
  (the intended workflow is fixing errors and regenerating, not absorbing)

### Requirement: Legacy ignore comments are preserved
The migration SHALL NOT modify existing `# type: ignore` or
`# pyright: ignore[...]` comments. New suppressions SHALL use
`# pyrefly: ignore[<rule>]` or bare `# type: ignore`.

#### Scenario: pyright ignores become inert, not errors
- **WHEN** pyrefly checks a line carrying `# pyright: ignore[...]`
- **THEN** the comment has no effect on pyrefly's diagnostics and no error is
  raised for the comment itself

### Requirement: Editors and agent sessions use the same engine
The repository SHALL provide configuration so that nvim and pi-lens agent
sessions run the pyrefly LSP for Python instead of pyright/mypy-based
checkers: a committed `.pi-lens.json` overriding the python LSP launcher and
covering the mypy/pyright diagnostic runners, and the nvim LazyVim
configuration enabling the pyrefly language server with pyright disabled.

#### Scenario: pi-lens defers mypy/pyright runners
- **WHEN** a pi-lens session analyzes a changed Python file
- **THEN** diagnostics come from the pyrefly language server and the
  mypy/pyright runners report covered/skipped

### Requirement: CI runs the type check
The CI lint job SHALL run `uv run pyrefly check` after the existing lint
steps, failing on any non-baselined type error.

#### Scenario: CI blocks a type regression
- **WHEN** a pull request introduces a new type error and does not update the
  baseline
- **THEN** the CI lint job fails

### Requirement: Invoke task exposes the check
The `inv check.types` task SHALL run `uv run pyrefly check`, and the default
`inv check` chain SHALL include it.

#### Scenario: Local check matches CI
- **WHEN** a developer runs `inv check`
- **THEN** the same pyrefly command CI runs executes locally and passes on an
  unchanged tree
