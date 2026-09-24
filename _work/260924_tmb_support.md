# TMB (Tour du Mont-Blanc) support

## Goal

Wire up the new `TmbService` (hut-services-private `main`, commit `8042422`,
PR #19) as a hut + availability/booking source, following the FFCAM pattern
(`_work/260920_ffcam_support.md`, PR #146). Source: montourdumontblanc.com —
the official booking platform of the Association des Gardiens du Tour du
Mont-Blanc (~43 huts — gîtes, refuges, auberges, hotels — in France, Italy
and Switzerland). Reverse-engineering notes: `hut-services-private/src/
hut_services_private/tmb/NOTES.md`.

## Changes

### `uv.lock`

- hut-services-private rev `6c37f30` → `8042422` ("Add Tour du Mont-Blanc
  (TMB) hut source with availability (#19)"). Also drops the now-unused
  types-beautifulsoup4 & friends (dependency cleanup from the uv migration,
  PR #18). `pyproject.toml` unchanged (already `branch = "main"`).

> **Correction (2026-09-24):** this bump never actually landed in #164 —
> the lockfile edit was made in the wrong checkout and reverted before
> commit, and the lane verification passed on the shared venv which
> happened to hold `8042422`. Fresh syncs from the merged lock installed
> the pre-TMB `6c37f30` (no `tmb` service). Restored in the worktree-safety
> PR (see `_work/260924_worktree_safety.md`).

### `server/apps/organizations/fixtures/organizations.yaml`

- New `tmb` org (pk 15, order 16): url https://www.montourdumontblanc.com,
  booking link pattern `https://www.montourdumontblanc.com/fr/refuges/{{id}}`
  (source_id is the URL slug; the per-day booking URLs are
  `/fr/reservation/{slug}/{YYYYMMDD}` and are built by the availability
  service, not the org pattern).
- Logo `tmb_icon.png` (256×256, PNG32): official TMB mark, derived from the
  site's `apple-touch-icon.png` (the header `tmb_logo.svg` is white-on-
  transparent — invisible on the admin's white). Committed in
  `server/apps/organizations/media/organizations/logos/` + `source/`.
- Colors: dark teal of the mark (`#0a5a54` / `#7fc7c0`).

### `server/apps/huts/management/commands/huts.py`

- `--add-all` source list: added `{"source": "tmb", "no_review": True}`
  after ffcam.

### No code changes needed elsewhere

- `settings.SERVICES` (common.py) merges `hut_services_private.SERVICES`
  automatically — `tmb` registers itself.
- `TmbService(support_booking=True)` → picked up by `update_availability`
  and the availability `AvailabilityService`.
- Hut merge logic, None-capacity handling (`free_unknown`), `is_bookable`
  all landed with FFCAM / hut-services 0.2.0.
- TMB hut types come from name-based rules + the core guesser; all resolved
  types (bhotel/hut/hostel/hotel/alp/closed/unknown) exist under the
  `accommodation` category parent.

## Verified (lane DB `feat_tmb_huts`, 2026-09-24)

Lane: `workz start feat/tmb-huts`, `workz sync <wt> --isolated`,
`scripts/lane-db.sh create feat_tmb_huts`, `scripts/sync-martin.sh`.

**Important:** verification commands must run via
`scripts/lane-run.sh .venv/bin/python manage.py <cmd>` — the `app` console
script resolves `server.*` through the shared venv's editable install
(pointing at the main checkout), while `manage.py` prepends the worktree cwd.
With plain `app` the lane silently runs MAIN-checkout code (symptom:
organizations fixture loaded without the new tmb entry).

1. `manage.py organizations --add --force` → "Created new entry
   'Tour du Mont-Blanc'" + logo upload.
2. `manage.py hut_sources --add --source tmb --force` → 43 hut sources
   created (matches NOTES.md inventory).
3. `manage.py huts --add --source tmb --no-review --force` → 39 created,
   3 updated (merged into existing huts by proximity), 1 no change.
4. `manage.py update_availability --source tmb` → 42/42 huts OK, 15,288
   day records + history (364 days × 42 huts), 0 failures, ~12 s.
   The 43rd hut (merged, e.g. `peule-peulaz` → lafouly.ch record) keeps
   its original availability source — correct merge behaviour.
5. Tests: `scripts/lane-run.sh .venv/bin/pytest` → 129 passed.

## Notes / open points

- The 33 MB availability page is fetched once per `update_availability`
  run regardless of source filter (service-level fetch); fine for the
  12 s runtime observed.
- Dev/prod imports still to run after merge:
  `app organizations --add --force`, `app hut_sources --add --source tmb`,
  `app huts --add --source tmb --no-review`, `app update_availability
  --source tmb` (then `app update_availability --all` picks tmb up
  automatically on subsequent runs).
- Logo is the apple-touch-icon upscale (173×180 → 256×256); swap for a
  crisp official asset if one becomes available.
