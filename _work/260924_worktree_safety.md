# Worktree lane safety: own venvs, checkout-aware app, lane DB cleanup

## Goal

Make workz lanes fully self-contained and remove the shared-venv footguns
discovered during the TMB lane (`_work/260924_tmb_support.md`): the `app`
console script silently ran main-checkout code inside worktrees, the shared
`.venv` symlink let any lane's `uv sync` re-point the shared editable
install for everyone, and `workz done --cleanup-db` failed to drop
branch-derived lane DB names.

## Changes

### `manage.py` — checkout-aware console scripts

`app` / `manage` (`[project.scripts]` → `manage:main`) live in the venv;
their imports resolved `server.*` from the venv's editable install, which
pins the main checkout. `_prefer_cwd_checkout()` prepends the working
directory when a `manage.py` exists next to the caller — the same thing
`python manage.py` does via `sys.path[0]`. No-op elsewhere (subdirs, non-
checkouts keep the editable fallback). With per-lane venvs this is defense
in depth: running the MAIN venv's `app` while standing in a worktree still
does the right thing.

### `.workz.toml` + `scripts/lane-venv.sh` — per-lane venvs instead of a shared symlink

- `[sync] ignore_add = [".venv"]`: workz no longer symlinks the shared venv.
- `post_start` runs `scripts/lane-venv.sh` first: `uv sync --frozen --extra
  private` (workz's own auto-install never fires for us — it requires no
  `.venv` anywhere; main always has one — and would run plain `uv sync`,
  which **silently omits hut-services-private**: settings swallow the
  ImportError and the booking sources vanish from `SERVICES`).
- The script also patches the lane venv's `activate` with a LANE-AWARE
  `app()`, defaulting to `scripts/lane-run.sh .venv/bin/python manage.py
  "$@"` (infisical, LANE database). The original function (`inv
  update-venv --infisical` → `app() { inv app.app -i --cmd "$*"; }`)
  wraps infisical, which injects the DEV database — wrong target inside a
  lane (.env.local is not in Django's env chain, which is why lane-run.sh
  re-injects POSTGRES_DB). The original task supports a no-infisical mode
  (`inv app.app` without `-i` → bare console script on the shell env);
  the lane function supports it too via `WODORE_APP_NO_INFISICAL=1`, still
  forcing `POSTGRES_DB`/`MARTIN_TILE_URL` from `.env.local` so local-env
  mode also targets the lane DB.
- No `make init` for lanes: its other pieces are covered — pre-commit hooks
  live in the shared `.git/hooks` (worktrees already run them), and
  `.volumes/pgdata` + `media/imagor_data` are only needed for local
  compose/imagor work (main checkout).
- Cost, measured: ~6 MB marginal disk per lane (uv hardlinks package files
  from `~/.cache/uv`; 635 MB venv size is an illusion — only ~6 MB are
  unique inodes), 0.2 s warm sync. Hardlinks require the venv to share a
  filesystem with the cache (worktrees under `/home/tobias` do).
- Why not keep the symlink: a shared venv's editable install pins the MAIN
  checkout on `sys.path` (the `app` bug), and any lane running `uv sync`
  re-points that editable to its own checkout — silently poisoning the
  main checkout's dev runs and every other lane.

### `scripts/lane-db.sh` — drop guard accepts workz-allocated names

The guard only accepted `pi_*` / `*lane*` patterns, but workz derives DB
names from the branch (`feat_tmb_huts` matched nothing), so
`workz done --cleanup-db` aborted and orphaned the lane DB (pre_done hook
failure — `workz done` removed the worktree anyway). The guard now also
accepts the name recorded in the worktree's own workz-managed `.env.local`
(`DB_NAME`) — that file is the authoritative allocation record. Protected
databases (`wodore`, `wodore_template`, system DBs) are still refused
unconditionally.

### `AGENTS.md`

Worktree section updated: own-venv bullet (with the `--extra private`
gotcha), lane step 1 now includes the venv sync.

## Verified (2026-09-24)

1. `manage.py`: from a test worktree root, `app shell -c "import server…"`
   resolves the worktree; from a subdir without `manage.py` and from the
   main checkout, behaviour unchanged; `inv tests` → 129 passed.
2. Lane verification (`workz start` on a temp branch, new provisioning):
   worktree got its own real `.venv` (not a symlink) via `lane-venv.sh`;
   activate carries the lane-aware `app()` — `app shell -c` reported the
   LANE database and lane code; `scripts/lane-run.sh .venv/bin/pytest` →
   129 passed; `scripts/lane-db.sh drop` (no arg, name from `.env.local`)
   now drops the lane DB; explicit `drop wodore` still refused.
   `lane-venv.sh` re-run is idempotent (no duplicate `app()`).
3. Teardown: `workz done <branch> --cleanup-db` now drops the lane DB
   through the widened guard.

## Notes / open points

- `infisical run --silent` swallows the CHILD's stdout too: `app
  createsuperuser` hung with invisible prompts after the username (root
  cause found by the user: removing `--silent` fixed it). Dropped `--silent`
  (kept `--log-level warn`) from `tasks/app.py`, `scripts/lane-run.sh` and
  the AGENTS.md alias doc.

- venv sync only happens via `post_start` (`workz start`) or manually —
  the pi provisioning `workz sync --isolated` path still needs lane step 1
  (documented in AGENTS.md).
- Cold-cache or changed-lockfile syncs cost seconds (git deps) to a
  minute — still fine per lane.
