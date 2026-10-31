# Proposal: external-actions

## Why

The map product knows *where* things are but not how to hand them off
to the apps users actually plan with. A clicked transit stop (Transitland
vector tiles, live since #452) carries everything needed to open a
journey planner — `adm0_iso` and the stop name ride on every tile
feature — yet the only cross-app hand-off anywhere in the product is a
bare `geo:` URI. Every journey-planner and map app has its own deep
link, none is universal, and hard-coding a Swiss-only picker (SBB, DB,
ÖBB) breaks the moment the map serves anywhere else — which it already
does (global huts, global stops).

The owner decision: a **generic "open-in" action registry** — curated
rows that say *which app*, *for which kinds of things*, *in which
countries*, each backed by a URL template the client renders with the
feature's own properties. New use cases become data, not code: journey
planners for stops, map apps (Google, Mapy, …) for any geoplace or
point, point-weather links for huts and peaks — all from one model, and
later user-created private actions on the same machinery.

## What Changes

- **New `ExternalAction` model** in `external_links` — a thin scoping
  row over the existing `ExternalLink` (which keeps owning the URL
  template, `{var}` placeholder machinery, i18n labels and health
  checks):
  - `link` FK → `ExternalLink`
  - `user` FK → user, nullable — `NULL` = public/curated row, set =
    user-owned private action (foundation for custom user actions)
  - `kinds` M2M → `Category` on the existing `map.*` kind tree — the
    "applies to" axis; **empty = any point, including category-less**
    (map long-press). Matching is by **kind identifier** (the 2-slug
    `Category.identifier`, unique per design) — no ancestor walks
  - `countries` JSON list of ISO-3166 alpha-2 codes — empty = global
  - `order`, `is_active`
  - partial unique constraints: one public action per link
    (`UNIQUE(link) WHERE user IS NULL`), no per-user duplicates
    (`UNIQUE(user, link) WHERE user IS NOT NULL`)
- **New public endpoint** `GET /v1/links/actions?kind=&iso=` — public
  rows only, anonymous, purely query-string-keyed, CDN-cacheable like
  the map catalog. `kind` takes the kind identifier (2 slugs);
  `iso` the country code the client already has on the feature
  (`adm0_iso` from the tiles).
- **New `/v1/my/` namespace** with `GET /v1/my/links/actions?kind=&iso=`
  — authenticated, user-owned rows only, `Cache-Control: private,
  no-store`. The namespace is the policy boundary: one route-level
  rule (auth + private + never CDN) makes the hut-page cache-poisoning
  class of bug structurally impossible for user-scoped responses.
- **Render endpoint** `GET /v1/links/actions/{identifier}?lat=&lon=&name=`
  — server-side `ExternalLink.render_url()` for contexts without client
  rendering (QR, e-mail, llms surfaces); owner-checked for user rows.
- **Seed** (~10 rows): planners SBB (CH), DB Navigator (DE), ÖBB (AT);
  global map apps Google Maps, Apple Maps, Mapy, Organic Maps; one
  point-weather link (meteoblue) as the genericity proof. Zero new
  category vocabularies — the kinds axis reuses the existing tree.
- Frontend consumption (stop popup + the generic "Open in…" picker) is
  a follow-up change; this change delivers the registry and its API.

## Capabilities

### New Capabilities
- `external-actions`: the open-in action registry — model, scoping axes
  (kinds/countries/user), the public CDN-cacheable list endpoint, the
  private `/my/` user endpoint, the render endpoint, and seed data.

### Modified Capabilities

None — purely additive. `ExternalLink` is referenced, not changed; no
existing endpoint's contract moves (additive endpoints need no API
version bump per the versioning runbook).
