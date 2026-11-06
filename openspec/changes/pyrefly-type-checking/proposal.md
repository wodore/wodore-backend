## Why

Static type checking has been a no-op since the project started: the
`[tool.mypy]` config sets `ignore_errors = "True"` (the django-stubs plugin was
never even configured), no checker runs in CI, and the `# pyright: ignore`
comments scattered over 68 files are suppressions for an editor LSP that was
never formalized. Meanwhile the tooling landscape moved on: Meta's pyrefly
(Rust, 1.x-stable since May 2026) ships first-party Django ORM type inference
in both its CLI and its LSP — verified on this codebase (`hut.id` → `int`,
`Hut.objects` → the custom `HutManager`) — at sub-second warm speed, which
mypy-with-plugin (~20s here) and ty (no Django support, astral-sh/ty#1018 open)
cannot match.

## What Changes

- **Adopt pyrefly as the project's single type checker** — one engine for CLI
  (`pyrefly check`), CI, and editor LSP, configured in `pyproject.toml`
  (`[tool.pyrefly]`), pinned exactly (`pyrefly==1.4.0`) because diagnostic
  behavior still moves between minor releases.
- **Remove all mypy and pyright tooling**: drop `mypy` from dev dependencies,
  delete the no-op `[tool.mypy]` block and `.mypy_cache/`, and rewrite the
  `inv check.types` task (currently `uv run pyright server` — a tool that
  isn't even a declared dependency) to run pyrefly.
- **Update django-stubs / django-stubs-ext `5.*` → `6.*`** (6.1.x tracks
  Django 6.1, which the project runs). django-stubs remains required: it
  supplies the Django type vocabulary that pyrefly's built-in ORM semantics
  build upon.
- **Existing errors are out of scope**: a committed baseline file
  (`pyrefly-baseline.json`) suppresses the ~329 current findings so CI starts
  green; only *new* type errors fail. Fixing the backlog is an explicit
  follow-up task.
- **Leave existing ignore comments untouched**: `# type: ignore` comments keep
  working (pyrefly honors them), `# pyright: ignore` comments become inert
  (pyrefly neither honors nor flags them). Their conversion/removal belongs to
  the follow-up fixing task, not this migration.
- **Wire the toolchain**: pyrefly step in the CI lint job; nvim (LazyVim)
  swaps pyright for the pyrefly LSP; pi-lens (agent sessions) overrides its
  python LSP launcher to pyrefly and makes its mypy/pyright diagnostic runners
  defer to it via a committed `.pi-lens.json`.

Non-goals: fixing the ~329 baselined type errors, converting or deleting the
~93 files carrying legacy ignore comments, enabling stricter presets
(`strict`/annotation-completeness rules), evaluating ty (revisit when
astral-sh/ty#1018 ships Django support), any runtime/API behavior change.

## Capabilities

### New Capabilities

- `type-checking`: the project's static type-checking contract — which tool
  checks Python code, how it is configured (pyproject, stubs version), how CI
  gates on it (baseline ratchet: no new errors), how editors/agents consume
  the same engine (nvim LSP, pi-lens), and the ignore-comment policy.

### Modified Capabilities

(none — no existing spec covers development tooling.)

## Impact

- **Dependencies** (dev group): `+pyrefly==1.4.0`, `mypy==1.*` removed,
  `django-stubs==5.*`/`django-stubs-ext==5.*` → `==6.*`; `uv.lock` updated.
- **pyproject.toml**: `[tool.mypy]` + `[[tool.mypy.overrides]]` removed;
  new `[tool.pyrefly]` section (includes `server/`, excludes migrations,
  baseline path, project search paths).
- **New files**: `pyrefly-baseline.json` (committed), `.pi-lens.json`
  (committed, project-level pi-lens config).
- **CI**: `main.yml` lint job gains a `pyrefly check` step.
- **Developer tooling**: `inv check.types` → pyrefly; `inv check` now includes
  types; nvim LazyVim python LSP pyright → pyrefly; pi-lens python server
  launcher → pyrefly LSP.
- **Zero runtime impact**: no application code changes, no API changes, no
  settings changes.
