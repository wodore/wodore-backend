# Tasks: pyrefly-type-checking

## 1. Dependencies & pyproject

- [x] 1.1 `pyproject.toml` dev group: remove `mypy==1.*`, add `pyrefly==1.4.0`, bump `django-stubs==5.*`→`==6.*` and `django-stubs-ext==5.*`→`==6.*`
- [x] 1.2 Remove `[tool.mypy]` + `[[tool.mypy.overrides]]`; add `[tool.pyrefly]` (project-includes `server`+`tests`, project-excludes migrations/caches/dotdirs, `search-path`, `python-interpreter-path`, `baseline`)
- [x] 1.3 `uv lock`; sync lane venv (`uv sync --extra private`); remove `.mypy_cache/`

## 2. Baseline

- [x] 2.1 Generate `pyrefly-baseline.json` via `pyrefly check --update-baseline`; verify `uv run pyrefly check` exits 0
- [x] 2.2 Exclude the baseline JSON from the prettier / end-of-file-fixer / trailing-whitespace pre-commit hooks (generated artifact, must not be reformatted)

## 3. Tooling wiring

- [x] 3.1 `tasks/check.py`: `types` task → `uv run pyrefly check`; add `types` to the default `check` chain and drop the "skipped" warning
- [x] 3.2 CI `main.yml` lint job: add `uv run pyrefly check` step
- [x] 3.3 Commit `.pi-lens.json` at repo root: override python LSP launcher → `pyrefly lsp` (via `uv run`), cover/defer mypy+pyright runners; verify with `effective_config` that pyrefly is selected and runners defer
- [x] 3.4 nvim LazyVim (`~/.config/nvim/lua/plugins/nvim-lspconfig.lua`): enable `pyrefly` server, disable `pyright`

## 4. Docs & verification

- [x] 4.1 AGENTS.md: short "Type checking" section (tool, commands, baseline policy, ignore-comment policy)
- [x] 4.2 Verify: `inv check.types` green, `inv lint` green (pre-commit with new excludes), pyrefly detects a planted new type error while baseline suppresses an existing one
- [x] 4.3 Full test suite via lane runner (no runtime changes expected)

## 5. Out-of-scope fix that became necessary

- [x] 5.1 `tasks/__init__.py`: replace sys.path-style `from _env import` / `from _logger import` with package-absolute `from tasks._env import …` so the package is statically resolvable; the import order is load-bearing (helpers must bind before submodules load) — pinned with `# isort: skip` markers; verified via `import tasks.check`, `inv --list`, `inv check.types`, `ruff check tasks/`
