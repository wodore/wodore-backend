# FFCAM Support (hut-services-private)

**Date:** 2026-09-20 / 21
**Status:** Done — full import (117 sources, 116 huts) + availability update verified live

## Goal

Wire up the new `FfcamService` (branch `feat/ffcam_huts` in `hut-services-private`)
as an editable local source, add the FFCAM organization, and make it usable as an
availability/booking source like HRS.

## Changes

### `pyproject.toml` (backend)

- `[tool.uv.sources]`: `hut-services-private` **and** `hut-services` switched from
  git to local editable paths (`/home/tobias/git/wodore/hut-services-private`,
  `/home/tobias/git/wodore/hut-services`).
  Both must be switched together: the private package declares
  `hut-services = [{ path = "../hut-services", develop = true }, ...]` (poetry
  dual source) and uv fails with "conflicting URLs" if the backend pins
  `hut-services` to git.
- Install with: `uv sync --extra private` (the `private` extra pulls in
  `hut-services-private`; plain `uv sync` does NOT install it).

### `server/apps/huts/models/_hut.py`

- `availability_source_ref` was set only for hardcoded `organization.slug == "hrs"`.
  Replaced with `is_booking_source(hut_source)` helper that **delegates to the
  service layer**: `service.is_bookable(source_properties)` — per-hut bookability
  lives with the service, not the backend.
  - `hut-services` `HutSchema.is_bookable: bool = False`: new field —
    "availability can be fetched for this hut via its source service".
    `BaseHutConverterSchema.is_bookable` computed field defaults to `False`;
    booking services override it in their converter:
    - `HrsHut1Convert.is_bookable` → `True` (all HRS huts bookable)
    - `FfcamHutConvert.is_bookable` → `bool(source_data.booking.structure_id)`
      (computed during conversion from the stored booking metadata — no extra
      service call, no inventory lookup)
  - Backend: `hut_schema.is_bookable` in `create_from_schema`/
    `update_from_schema` decides `availability_source_ref`. The earlier
    `BaseService.is_bookable()` / `is_booking_source()` indirections were
    removed — the flag rides the existing `convert()` call.
  - 27 wrongly flagged huts were cleaned up once via script.
  ⚠️ The hut-services change needs a version bump/publish before deploying
  (backend git pin must include `HutSchema.is_bookable`).
- Base `name` field was never populated on import (only `name_de`/`name_fr`/...).
  New `primary_name()` helper fills the base name (priority de→en→fr→it) on
  create and on update (only when empty — existing names are never overwritten).
  Fixes 107 ffcam huts that had `name=''` while `name_fr` was set (old refuges.info
  huts have base names; consistency + search/sort on `name`).

### Merge logic (how imports match existing huts)

`Hut.update_or_create` matches **purely on location**: nearest hut within 30 m
(no name/slug matching; slug is generated from `name_i18n` for new huts only).
Verified with the full ffcam import: 9 merged huts are all genuine same-hut
matches (albert, argentiere, couvercle, dent-oche, leschaux, alpin-tour, tuffes,
gros-morond, ratou — Chamonix/Jura border huts that SAC also lists), 0-2 m apart.
- `couvercle` vs pre-existing `couvercle-winter-only` (84 m): separate entries,
  pre-existing, left as is.
- new `souffles1` (Refuge des Souffles) vs pre-existing `souffles` (Abri des
  Souffles, 226 m): distinct objects, correctly NOT merged.

### `server/apps/organizations/fixtures/organizations.yaml`

- New `ffcam` org (pk 14, order 15): url ffcam.fr, booking link pattern
  `https://centrale.ffcam.fr/index.php?structure={{props.structure_id}}`
  (the structure id lives in the hut source properties; source_id itself is the
  ffcam slug, e.g. `refugedelaigle`).
- Logo: placeholder `ffcam_icon.png` (blue mountain, PIL-generated, 256×256 in
  `media/organizations/logos/` + `source/`) — **replace with the official logo**
  (no network available during this session), then `app organizations --add --force`.

### `server/apps/huts/management/commands/huts.py`

- `--add-all` pipeline: added `{"org": "ffcam", "no_review": True}`.

### FFCAM availability with unknown totals (None handling)

`hut-services` `PlacesSchema` returns `free`/`total`/`occupancy_*` = `None` when
the source does not publish them (FFCAM bookable days often have free counts but
no totals; occupancy then is `free_unknown`). The backend assumed non-null:

- `server/apps/availability/services.py`: `b.places.total <= capacity_closed`
  crashed with `TypeError` on None → added `is not None` guard.
- `server/apps/availability/models.py` + migration `0010`: `free`, `total`,
  `occupancy_percent`, `occupancy_steps` nullable on `HutAvailability`
  (and `free`/`total`/`occupancy_percent` on `HutAvailabilityHistory`).
  `null` in DB = "not published by source", NOT 0!
- `server/apps/huts/schemas_booking/_booking.py` and
  `server/apps/availability/schemas.py`: `free`/`total`/`occupancy_percent`/
  `occupancy_steps` now `int | None`/`float | None` (API fields can be null).
- `server/apps/availability/admin.py`: occupancy helpers handle None
  (`get_occupancy_progress_bar` renders the "?" bar when occupancy is not
  computable; `places_display` shows "–" instead of "None" for unknown
  free/total) — fixes a TypeError (500) on the hut change page and the
  availability changelists for FFCAM huts.

### `hut-services-private` (user's repo, branch `feat/ffcam_huts`)

- `__init__.py`: added `FfcamService` export (`from hut_services_private import
  FfcamService` now works; `SERVICES` already contained it).

## Verified

- `settings.SERVICES` contains `ffcam` (merged via `PRIVATE_SERVICES`), `support_booking=True`.
- `app organizations --add --force` creates/updates orgs incl. FFCAM.
- **Full import** `hut_sources --orgs ffcam` → 117 sources (114 created, 3 unchanged);
  `huts --add --org ffcam --no-review` → 116 huts (107 created, 9 merged into existing,
  0 failed).
- `manage.py update_availability --all` → full run over all 242 availability huts
  (153 hrs + 89 ffcam) + retry of failed batches. Final: **89/89 ffcam huts with
  data (32,485 rows)**, 147 hrs huts updated; 7 pre-existing hrs no-data huts
  remain failing (faulhorn, britannia, gorda, dal-linard, etzli2, tiefenbach,
  caviano — 30-60 accumulated failures long before ffcam; AvailabilityStatus
  tracking handles them by design).
- `inv tests` → 8 passed.

## Full import details (2026-09-21)

- 117 FFCAM hut sources, all with location; 89 bookable (structure_id),
  28 without online booking structure (Mont-Blanc portal huts like Goûter,
  Tête Rousse, external-website huts like Baerenkopf).
- Fixed during import:
  1. `availability_source_ref` was set for ALL ffcam huts — now only for bookable
     ones (per-hut `structure_id` check, service-side); 27 wrongly flagged
     huts cleaned once via script.
  2. Base `name` field was empty on all 107 new huts (only `name_fr` set) —
     `primary_name()` now fills it (de→en→fr→it priority; existing names never
     overwritten). Re-import filled all 107.
  3. `HutBookingSchema.link` was non-optional — FFCAM returns `link=None` for
     closed days (`_day_booking_link` skips closed states), so ONE hut with winter
     closures failed pydantic validation and poisoned its whole 30-hut batch
     ("Batch fetch error: 96 validation errors"). Made `link: str | None` (storage
     already used `booking.link or """).
- Type-checker fixes along the way: explicit `hut_sources`/`_orig_*` annotations +
  `RelatedManager` TYPE_CHECKING import in `_hut.py`, `Position2D` construction in
  `schemas_booking/_booking.py`, `update_availability.py` (profiler init, option
  fallbacks, int() coercions, fetch/process task mixup in progress callbacks).

## FFCAM totals & hut types (2026-09-21, follow-up)

FFCAM booking calendars **never publish totals** (NOTES.md: guarded total
comes from the search card "N places", the winter/hors-gardiennage total only
from the per-hut minisite info box). Two gaps fixed:

1. `FfcamService.get_bookings` built the slug→structure mapping but never
   passed `guarded_beds`/`winter_beds` to `get_hut_bookings` — now collects
   them per hut (`source_data.guarded_beds` card fallback, `winter_beds` from
   the minisite via `get_huts_from_source(with_minisite=True)`, file-cached)
   and passes them → totals on every bookable day inside the published
   window → computable occupancy.
2. `hut_sources` command gained `-m/--with-minisite` to store minisite data
   in `source_data` → hut `capacity_closed` (winter beds) and reduced hut
   types after re-import: **75 selfhut + 3 bivouac** (27 huts without
   published winter data legitimately keep none).

Re-run: `hut_sources --orgs ffcam --add --with-minisite` →
`huts --add --org ffcam --no-review` → availability update (89/89 huts, 0
failed). Result: 2,159 rows with totals (5–95 beds), 2,050 with computable
occupancy (empty/low/medium/high/full), reduced types on offseason days
(selfhut 1,132 / closed 685 / bivouac 92 rows). Remaining `total=None` rows
are genuinely unpublished: far-future dates beyond the calendar window
(FFCAM publishes ~6 months ahead), `not_online` quota-exhausted and closed
days. 25 bookable huts are between seasons — calendars currently return
nothing at all (verified ecrins live), totals appear once FFCAM opens sales.

### Reduced types for ALL huts (2026-09-21)

`FfcamHutConvert.closed_hut_type` fallback chain extended: guesser →
(winter beds published → selfhut) → **unknown** (winter operation not
published — e.g. Mont-Blanc portal huts run in winter via their own
reservation system, so `closed` would be wrong) → None only for unstaffed
open types (selfhut/bivouac). Final: 76 selfhut + 3 bivouac + 23 unknown,
and the 14 without a reduced type are all selfhut-open (unguarded
year-round) — exactly the intended rule. Note: 3 merged huts (gros-morond,
ratou, grand-ventron) had stale `hut_type_open=hut` from their original OSM
import while FFCAM classifies them selfhut — synced surgically; a general
type re-sync is possible via `huts --add --org ffcam -w -n hut_type`.

Also: availability admin None handling (occupancy "?" bar, `–` for unknown
free/total) after a TypeError on the hut change page.

## Dev env notes

- `infisical run` can hang when its API is unreachable; the CLI backup
  (`~/.infisical/secrets-backup/`) is encrypted and NOT usable directly.
  Workaround for local commands (docker compose defaults):
  `POSTGRES_DB/USER/PASSWORD=wodore DJANGO_DATABASE_HOST=localhost
  DJANGO_DATABASE_PORT=5432`.
- Without full infisical env, `django.setup()` intermittently takes minutes:
  the OIDC component tries to fetch `https://notset/.well-known/...` (DNS
  timeout variance). Harmless — wait or provide the proper OIDC env.

## Notes / open points

- **Shared huts** (listed by both HRS/SAC and FFCAM, e.g. Albert 1er on the
  French border): `availability_source_ref` supports only ONE source; the last
  import wins (existing hut `albert` switched hrs→ffcam). If dual-source huts
  become common, the model needs a priority concept.
- Full import run:
  `app hut_sources --orgs ffcam` → `app huts --add --org ffcam --no-review` →
  `app update_availability --all`. First run of the ffcam service builds a
  minisite→structure cache (~1 request per hut).
- FFCAM booking engine does not publish bed totals per day unless minisite data
  is fetched (`with_minisite=True` on `get_huts_from_source`); totals therefore
  often stay None — by design, see `free_unknown` handling above.
- Revert to git sources for deployment: swap the two `[tool.uv.sources]` entries
  back and `uv sync --extra private` (CI uses
  `uv sync --extra private` already, see `.github/actions/setup-venv`).
