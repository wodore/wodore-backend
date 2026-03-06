---
draft: false
date:
  created: 2026-03-06
  updated: 2026-03-06
slug: wep008
categories:
  - WEP
  - Places
  - OSM
tags:
  - wep008
  - geoplace
  - import
---

# `WEP 8` GeoPlace Extensions & Amenity Import

Extend `GeoPlace` with typed detail models and import amenities from OSM.
<!-- more -->

## Motivation

`GeoPlace` currently covers huts and natural features, but lacks structured data
for amenities relevant to Alpine tours: food supplies, transport, emergency
services, and accommodation. This WEP introduces typed detail models, per-source
import policies, and an automated OSM import pipeline.

## GeoPlace Extensions

Rather than adding all fields to `GeoPlace` directly, we introduce lightweight
OneToOne detail models per place type. `GeoPlace` itself gains a few shared
fields.

**New fields on `GeoPlace`**

| Field | Description |
|---|---|
| `slug` | Unique URL identifier |
| `description` | Long-form text (i18n) |
| `review_status` | Editorial state: `new / review / done / work / reject` |
| `review_comment` | Internal reviewer note |
| `detail_type` | Which detail model is attached: `amenity / transport / admin / natural / none` |
| `protected_fields` | JSON list of field names no source may overwrite |

`protected_fields` is maintained automatically — whenever a field is edited via
the Wodore admin or API, its name is appended to the list. Falls back to a
minimal global default of `["name", "location"]` when empty. Also editable
manually in the admin.

`detail_type` is a fixed enum tied to the available detail models — not derived
from category. Categories remain flexible (new category slugs can be added
freely). The mapping between a category and its `detail_type` lives in code.
`GeoPlace` exposes factory methods (`create_amenity`, `create_transport`, …)
that set `detail_type` and create the corresponding detail row atomically.

Natural features (peaks, passes, lakes, glaciers) have `detail_type=natural`
but no detail model — the category slug and existing `GeoPlace` fields
(location, elevation, name, `parent`) are sufficient. Mountain ranges and
administrative regions are represented via the `parent` self-FK.

**`AmenityDetail`** — food, shops, restaurants, emergency, accommodation

| Field | Description |
|---|---|
| `operating_status` | `open / temporarily_closed / permanently_closed / unknown` |
| `opening_months` | Monthly availability per month: `yes / yesish / maybe / no / noish / unknown` |
| `opening_hours` | Structured weekly hours per weekday + public holidays |
| `websites` | List of URLs with optional labels |
| `phones` | List of phone numbers |
| `extra` | Category-specific overflow (JSON) |

**`TransportDetail`** — bus stops, train stations, cable cars

| Field | Description |
|---|---|
| `station_id` | External identifier (e.g. Swiss DIDOK, UIC station code) |
| `operator` | Operating company (e.g. SBB, PostAuto, RhB) |

Connects naturally to GTFS integration (see WEP003).

**`AdminDetail`** — cities, villages, valleys

| Field | Description |
|---|---|
| `admin_level` | OSM admin level (2 = country … 10 = village) |
| `population` | Inhabitant count |

## Category Hierarchy

Categories follow a `parent.child` slug pattern. The mapping to `detail_type`
is defined in code and is not a hard DB constraint — categories stay flexible.

| Example categories | Typical `detail_type` |
|---|---|
| `natural.*` (peak, pass, lake, glacier, waterfall, waypoint) | `natural` |
| `admin.*` (city, village, valley) | `admin` |
| `food_supply.*`, `restaurant.*`, `accommodation.*`, `emergency.*` | `amenity` |
| `mobility.*` (bus_stop, train_station, cable_car, parking) | `transport` |
| `mobility.*` (bike_repair, bike_rental) | `amenity` |

The `Hut` model is not migrated as part of this WEP and continues to coexist.

## Source Tracking & Import Policy

All source-related data lives in `GeoPlaceSourceAssociation`, extended with:

| New field | Description |
|---|---|
| `modified_date` | Last time this source updated the record (set on every import run) |
| `update_policy` | How this source may update the record |
| `delete_policy` | What happens when this source no longer includes the record |
| `priority` | Source precedence for field conflicts — lower number wins (e.g. 1=OSM, 2=Overture) |

`import_date` (already exists) records the first import from a source.
`modified_date` records the most recent update.

The `wodore` source is the built-in manual edit marker. Whenever a place is
edited via the Wodore admin or API, two things happen automatically:

1. `wodore.modified_date` is set — replaces the existing `is_modified` boolean
2. The edited field name is appended to `place.protected_fields`

Import commands respect two levels of field protection:

- **`place.protected_fields`** — fields no source may ever overwrite (manually curated)
- **`priority`** — when two sources both provide the same non-protected field, the lower priority number wins. Higher-priority sources fill fields first; lower-priority sources only fill what remains.

**`update_policy`**

| Value | Behaviour |
|---|---|
| `always` | Always overwrite all fields |
| `merge` | Skip fields already edited by the `wodore` source |
| `protected` | Never overwrite |
| `auto_protect` | Behaves as `merge` until `wodore.modified_date` is set, then switches to `protected` |

**`delete_policy`**

| Value | Behaviour |
|---|---|
| `deactivate` | Set `is_active=False` |
| `keep` | Ignore deletion |
| `delete` | Hard delete |
| `auto_keep` | Behaves as `deactivate` until `wodore.modified_date` is set, then switches to `keep` |

## Multi-source Deduplication

When importing from a new source, each record must be matched against existing
`GeoPlace` entries before creating a new one. Matching logic lives in each
import script. The shared lookup order is:

1. **Source + source_id** — if this source has already imported this record
   (association exists), update in place. This ensures manually reviewed records
   are never re-duplicated on subsequent runs.
2. **External ID cross-reference** — some sources carry IDs from other sources
   (e.g. Overture stores `osm_id`). If a match is found via another source's
   `source_id`, associate and update according to policy.
3. **Location + category parent** — match within a defined radius and same
   category parent slug (e.g. `accommodation`). Tolerant of type differences
   between sources (e.g. `hut` vs `unattended_hut`).
4. **Location + very small radius** — no type match possible. If one candidate
   → associate. If multiple candidates → set `review_status=review` on all,
   keep records separate until manually resolved.

Run order determines effective priority — whichever source runs first creates
the `GeoPlace`. Subsequent sources associate to it and fill non-protected fields
according to their `update_policy` and the place's `priority` ordering.

**Staging table (future option)**

For higher data quality requirements or frequent re-imports, a lightweight
staging table can be introduced between fetch and merge:

1. **Fetch** — import all source records into a staging table (`location` + `source_data` JSON)
2. **Merge** — run the deduplication and upsert logic against `GeoPlace`
3. **Cleanup** — delete staging rows, or keep for diff tracking and review

This separates the raw import from the merge decision, makes diffs between runs
easy to compute, and allows a review step before anything touches `GeoPlace`.
Currently used for huts. For lower-stakes places (bakeries, bus stops) the
direct upsert approach is sufficient — staging can be introduced per source if
conflict rates or data quality requirements justify it.

## Data Import

`GeoPlace` and its detail models are populated via Django management commands,
one per source. Import logic is source-agnostic at the model level — factory
methods (`create_amenity`, `create_transport`, …) are reused regardless of source.

**Import run**

1. **Upsert** — iterate all records from the source. For each record, check
   `update_policy` on the association and create or update `GeoPlace` + detail
   model accordingly. Set `modified_date` on the association.
2. **Cleanup** — after the upsert pass, find all associations for this source
   where `modified_date` is older than the current run (i.e. not seen in this
   import). Apply `delete_policy`: deactivate, hard delete, or keep as-is.

This two-pass approach means every import is a full sync — no need to track
diffs externally.

**Sources**

- **OSM** (primary for amenities) — weekly CronJob fetching Alps PBF from
  Geofabrik, filtered with `osmium-tool`, parsed with `pyosmium`. Good rural
  and Alpine coverage, includes `opening_hours`. Upsert key: `(osm_id, osm_type)`.
- **GeoNames** (currently implemented) — natural features and admin places.
- **Overture Maps** (future) — potential supplement for places with low OSM
  coverage.

## API

Each `detail_type` gets its own endpoint with a fixed, fully-typed response
shape. `geo/places/{id}` always returns base fields only — no nullable detail
blobs, no discriminated unions.

| Endpoint | Response | Notes |
|---|---|---|
| `geo/places/search` | Base fields, paginated | Existing endpoint |
| `geo/places/{id}` | Base `GeoPlace` fields | Lightweight, all types |
| `geo/amenity/{id}` | Base + `AmenityDetail` | Food, shops, emergency, accommodation |
| `geo/transport/{id}` | Base + `TransportDetail` | Bus stops, stations, cable cars |
| `geo/admin/{id}` | Base + `AdminDetail` | Cities, villages |
| `geo/natural/{id}` | Base fields | Same as places for now, reserved for future |

`detail_type` on the base response tells the client which typed endpoint to
call for full details.

**Map layers (Martin)**

For vector tile serving via Martin, a PostgreSQL view is created per logical
map layer (e.g. `v_layer_food_supply`, `v_layer_transport`,
`v_layer_emergency`). Each view joins `GeoPlace` with the relevant detail model
and exposes only the fields needed for filtering and rendering. `detail_type`
and the category slug are always included for client-side style rules.

## Notes

A lightweight `Note` model is planned to attach time-stamped annotations to any
`GeoPlace` (e.g. "hut burned down", "source dry in summer"). Notes will carry a
severity level and an optional expiry. This is deferred and will be designed
separately.

## Out of Scope

- Point review workflow and OSM editing integration (Mangrove, MapComplete) — see WEP 009.
- `Hut` model migration into `accommodation.hut` — deferred, no timeline.
