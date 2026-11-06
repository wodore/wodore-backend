# Design: pyrefly type checking

## Context

Django 6.1 backend (~95k LoC Python in `server/`, 741 files of which 316 are
generated migrations, ~30 apps, heavy pydantic/msgspec/django-modern-rest
usage, custom model managers). Typing state today: ~45% of defs return-annotated,
zero enforcement. mypy configured to `ignore_errors = True` (no-op, plugin
never set up); no CI type job; ~68 files carry `# pyright: ignore[...]` from
historical Pylance use (author now works in nvim); 25 files carry
`# type: ignore`.

Tool decision (measured on this codebase, Oct 2026 — see
`_work/261024_django_type_checking.md`):

| | pyrefly 1.4 | mypy + django-stubs plugin | ty 0.0.91 |
|---|---|---|---|
| Django ORM | built-in (fields, `id`/`pk`, custom managers, FK/M2M forward, choices) | complete via plugin | none (astral-sh/ty#1018 open) |
| speed on `server/` | ~4s cold / <1s warm | ~20s | 2.6s |
| LSP | same binary (`pyrefly lsp`) | none | same binary, Django-blind |
| baseline ratchet | native (`--update-baseline`) | third-party | none |

## Goals / Non-Goals

Goals: one type-checking engine across CLI/CI/nvim/pi-lens; green CI from day
one without fixing legacy errors; no changes to application code.

Non-Goals: fixing the ~329 baselined errors; touching legacy ignore comments;
stricter presets; ty evaluation.

## Decisions

1. **pyrefly over mypy/pyright/ty.** Django inference + speed + LSP parity.
   django-stubs stays (pyrefly's ORM semantics build on the stubs' type
   vocabulary — verified: without stubs, `hut.id` degrades to `Unknown`).
   Rejected: mypy+plugin (slow, plugin value already hand-rolled in this
   repo's annotations, modeltrans/computedfields are plugin-blind anyway);
   pyright (no Django semantics — would keep the hand-annotation tax forever);
   ty (no Django story; revisit when #1018 lands — switching later costs ~a
   day since bare `# type: ignore` and Python annotations are portable).
2. **Pin `pyrefly==1.4.0` exactly.** Diagnostic rules still move between
   minor releases; upgrades must be deliberate (re-run, re-baseline if
   needed), not silent.
3. **`default` preset + baseline, not `basic`/`strict`.** Default gives the
   correctness tier (~329 findings incl. `bad-*`, `unbound-name`); `strict`
   adds ~1,900 annotation-completeness findings that are follow-up material.
   The committed baseline suppresses existing findings so only **new** errors
   gate. Pyrefly still shows baselined errors in the IDE — intentional: they
   stay visible for the fixing campaign without failing CI.
4. **Config in `pyproject.toml` (`[tool.pyrefly]`)**, not a separate
   `pyrefly.toml` — one less root file; pyrefly reads both (separate file
   would also take precedence and drift).
5. **Exclude migrations from checking** (316 generated files; mypy-era
   tooling excluded them too via error volume, pyrefly excludes them here).
   `server/` and `tests/` included.
6. **Legacy ignore comments stay.** `# type: ignore` is honored by pyrefly
   (verified) and is the portable dialect for any future checker; pyright
   comments are inert but harmless. Mass-editing 93 files would pollute this
   migration's diff and conflict with the follow-up fixing task that will
   delete most of them anyway. New code uses `# pyrefly: ignore[code]` or
   bare `# type: ignore`.
7. **Editor/agent wiring is part of the change** — a checker nobody sees is a
   checker nobody runs: nvim (LazyVim) drops pyright for `pyrefly` LSP;
   pi-lens overrides its python LSP launcher to pyrefly and marks mypy/pyright
   runners covered, via committed `.pi-lens.json` (project-scoped, so every
   worktree/agent session inherits it).
8. **`inv check.types` runs `uv run pyrefly check`** and joins the default
   `inv check` chain (now that it's green via baseline and fast).

## Risks / Trade-offs

- [pyrefly is young (1.x since May 2026); diagnostics may shift on upgrade]
  → exact pin; upgrades are a conscious task with re-baselining.
- [Reverse relations & advanced QuerySet ops not yet inferred] → repo's
  existing `hut_sources: "RelatedManager[HutSource]"` annotations remain the
  pattern (pyrefly honors declared annotations); gaps surface as `Unknown`
  (less precision), not errors.
- [Baseline can mask moved-but-not-fixed errors under default `column`
  matching] → shrink the baseline deliberately via `--update-baseline` in the
  follow-up fixing task; never as part of unrelated PRs.
- [`.pi-lens.json` launcher depends on `uv run` from repo root] → pi-lens
  launches language servers with the project as cwd; if the launcher ever
  fails, agents fall back to tree-sitter/ruff signals (no hard dependency).
- [Django 6.1 stubs lag] → `django-stubs 6.1.x` tracks Django 6.1; stubs
  drift degrades to `Unknown`, it does not crash (unlike mypy plugin version
  coupling).

## Migration Plan

Single PR, no runtime impact: dependency changes → config → baseline
generation → tooling wiring → CI. Rollback = revert the commit; nothing
persists outside the repo (lane venvs resync from the lockfile).

## Open Questions

None blocking. Follow-up candidates tracked outside this change: baseline
burn-down cadence; whether to enable `strict`-family rules per-app once the
backlog shrinks.
