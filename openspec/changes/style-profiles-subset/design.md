# Design: style-profiles-subset

## Context

The catalog serves map layers from Django (`basemaps`): `MapLayer` rows are
device-tier variants keyed `(slug, spec)` with `spec ∈ low|medium|high`
(`models.MapLayer.Spec`), enforced by the `unique_slug_spec_variant`
constraint; resolution is server-side via `SPEC_FALLBACKS` chains and
`MapLayer.pick_variant(queryset, spec)` — exact tier → explicit chain →
single remaining variant. `resolution.style_endpoint_url(slug, spec)` builds
`/v1/map/styles/{slug}.json?spec=…`; the layers/layer-detail/style/catalog
endpoints all share that walk and report the served `spec`
(`api.MapLayerEntry`, one resolved row per slug — the #331 contract).
Validation today is structural only (`validation.validate_style_spec`:
`version == 8`, sources object, `{id, type}` layers).

The frontend's no-WebGL fallback map (frontend PRs #352, #359) renders the
catalog on a Leaflet engine. Leaflet-class engines can only render a strict
subset of the MapLibre style spec, so the frontend currently *guesses*
compatibility by inspecting served styles and keeps hardcoded palette
copies. Nothing in the data model expresses renderer capability, and
nothing machine-checks the guess.

This change adds that second dimension — `profile` (full vs strict subset)
— plus the `version` field recording which rules a document was validated
against, a capability parameter on the API, the subset whitelist itself, a
clustering rendering hint in layer config, and the validation pipeline
that makes every claim checkable.

Everything below was settled with the owner in a frontend work session;
this document structures the decisions and grounds them in the code.
Discrepancies between the session's assumptions and actual code are
collected in "Code-reality discrepancies" at the end.

## Goals / Non-Goals

Goals:

- Renderer compatibility becomes **server-authored and explicit** — a
  `profile` on the variant row, not a client-side style inspection.
- A **strict, machine-checkable subset definition** (v0.1) that a
  Leaflet-class engine can render and that is a valid full MapLibre style
  by construction.
- **Capability-based resolution** without breaking the one-resolved-row
  contract or existing clients (#331): `?profile=` is optional and
  additive.
- **Clustering hints in layer config** — renderer data (what to group by,
  how to bubble), not style-document extensions.
- **Validation gates**: full rows validated against the real MapLibre
  style spec (styl, CI-only), subset rows against our own whitelist
  (pure-Python, save/seed/CI) — no Node in the server runtime.

Non-Goals:

- No MapLibre→Leaflet compiler (rejected: rebuilds MapLibre).
- No 4th spec tier (`noglu`/`nogpu`) — rejected: renderer capability ×
  device tier are orthogonal dimensions.
- No renderer-named profiles (`maplibre`/`leaflet`) — rejected: a subset
  style does not require Leaflet; `full`/`subset` name the *format
  richness* of the document.
- No auto-tagging of profiles at serve time (rejected: one-time manual
  seeding is enough; the walker sweep catches drift in CI).
- No clustering inside the style document — not even x-prefixed vendor
  keys (rejected: `cluster` is only legal on geojson sources in the
  MapLibre spec; on a vector source it would break subset validity).
- No availability-state-differentiated unclustering in v0 (app-state
  dependent; single `maxZoom`).
- No change to the style document's internal `"version": 8` field.

## Decisions

### D1 — `profile` is a capability dimension of the variant row

`MapLayer` gains `profile ∈ {full, subset}` (`TextChoices`, default
`full`, DB check constraint `basemaps_maplayer_profile_valid` mirroring
`basemaps_maplayer_spec_valid`). Key properties:

- **Not a 4th spec tier.** `spec` answers "what device tier is this
  variant for"; `profile` answers "how rich is the format". A slug can
  exist as `(medium, full)` *and* `(medium, subset)` — two rows, same
  tier, different format richness.
- **Not renderer names.** A `subset` document is a strict subset of the
  MapLibre style spec — valid as a full style by construction, renderable
  by a simpler engine. Any full-capable client (MapLibre or otherwise) can
  consume a `subset` row; that is what makes the fallback chains below
  safe.
- Uniqueness moves from `(slug, spec)` (`unique_slug_spec_variant`) to
  `(slug, spec, profile)` (constraint `unique_slug_spec_profile_variant`).

### D2 — `version` records the rules a document was validated against

`MapLayer` gains a `version` string (char, short). Semantics:

- `full` rows: the `@maplibre/maplibre-gl-style-spec` release the document
  was validated against (e.g. `26.4.4` — the package version bundled by
  the styl validation in CI, see D6).
- `subset` rows: our subset revision (e.g. `0.1`). When the whitelist
  evolves, the revision bumps and `subset` rows re-validate against the
  new rules.
- The style document's internal `"version": 8` field is **untouched** —
  `validation.validate_style_spec` keeps enforcing 8 for both profiles.
- Inline `style` rows are required to carry a `version`; externally
  authored `style_url` rows may leave it empty (not our document — same
  stance as the payload's `style_version` cache token, which is null for
  external styles).

### D3 — Capability-based resolution: the 2D walk

Clients declare capability with `?profile=full|subset` on the layers,
layer-detail, style and catalog endpoints (omitted = today's behavior —
profile-agnostic tier walk; fully backward compatible with #331 clients,
who never see a different body unless a subset variant displaces a missing
full one, which is safe by D1's validity-by-construction).

`SPEC_FALLBACKS` stays the tier-chain source of truth; the walk nests the
profile dimension inside it. For a client wanting tier `T`:

| Client capability | Walk order |
| --- | --- |
| `profile=full` | `full@T` → `subset@T` → `full@T′` → `subset@T′` → … (T′ iterate `SPEC_FALLBACKS[T]`) |
| `profile=subset` | `subset@T` → `subset@T′` → `subset@T″` → … — **never `full`** |
| omitted (today) | first active row per `[T, *SPEC_FALLBACKS[T]]`, profile-agnostic |

Rules:

- **Tier is a device constraint and is respected before format richness**:
  a full-capable client prefers any profile at its wanted tier over any
  profile at a degraded tier; within a tier it prefers `full` over
  `subset`.
- A subset-only client never receives a `full` row: a slug without any
  `subset` variant is absent from its resolved catalog view and 404s on
  the style/detail endpoints (the subset basemap ladder exists — see the
  tagging table: `world-topo` is subset).
- `pick_variant(queryset, spec)` gains a `profile` parameter implementing
  the table; the one-resolved-row contract is preserved and the payload
  reports what was served: existing `spec` plus new `profile`/`version`.
- `resolution.style_endpoint_url(slug, spec)` becomes
  `style_endpoint_url(slug, spec, profile)`; `style_url` in the payload
  echoes the resolved profile **only when the request carried the
  `profile` parameter** — a request without it must produce a
  byte-identical payload to today's (#331 strict compat), so the
  parameter is appended to `style_url` exactly when the client sent
  it. `get_map_style` parses `profile` either way. The Martin-parity
  catalog resolves `profile` into `path` the same way.
- Cache correctness folds in **automatically** once `pick_variant`
  honors the parameter — no new memo inputs. For the layers, detail,
  slots and catalog endpoints, `etag_page` already hashes the full
  sorted query string into the ETag and body-cache key
  (`controller.py`), so `?profile=` gets its own identity per existing
  machinery. For the style endpoint, `_style_cache_key` is per **row**
  (`layer.pk`, `layer.spec`, …) — a different profile resolves to a
  different variant row and therefore a different key. The only
  required change is that `get_map_style` passes the parsed `profile`
  into `pick_variant` (today it reads only `spec`). (Deliberately NOT
  folded into the *Caching and API contract* requirement: that
  requirement is concurrently modified by the active
  `tile-asset-versioning` change; this change's archive must sequence
  after that one and merge, not clobber, its ETag input list.)

### D4 — Subset profile v0.1: the strict whitelist

A `subset` v0.1 document is a MapLibre style (`version: 8`) restricted
to — the human-readable mirror with worked examples and maplibre
spec-links is [`docs/map-style-subset-spec.md`](../../../docs/map-style-subset-spec.md):

**Top-level keys** — `version`, `name`, `metadata`, `sources`, `sprite`,
`glyphs`, `layers` (glyphs/sprite may be present even when unused —
seeded raster styles carry an unused `glyphs` reference).

**Sources** (closed key sets per type):

| Type | Allowed keys |
| --- | --- |
| `raster` | `type`, `tiles`, `maxzoom`, `tileSize`, `attribution` |
| `vector` | `type`, `tiles`, `minzoom`, `maxzoom`, `attribution`, `encoding` (value `mlt`) — inline MLT tile URLs (`.mlt` URL space) with the MapLibre decoder marker, one `source-layer` consumed by the layers; no TileJSON `url` links (the huts overlay already moved to inline `tiles` in tile-asset-versioning). `encoding: mlt` is a wodore/Martin extension to the style spec — one deliberate qualification of "valid full MapLibre style by construction" for vector-MLT sources (every full renderer we ship consumes it; stock validators ignore unknown source keys) |
| `geojson` | `type`, `data` — data URL string; `{{token}}` runtime params allowed inline (e.g. `?date={{date}}`) |

`promoteId` is deliberately **not** whitelisted (clients key features by
the tile-provided id), and neither is the TileJSON `url` form.

**Layers** — `id`, `type`, `source`, `source-layer`, `minzoom`, `maxzoom`,
`paint`, `layout` with:

- Layer types: `raster`, `circle`, `symbol` (sprite-pack icon + simple
  text).
- Circle/raster layers: no `layout` keys.
- Symbol `layout` keys: `icon-image`, `icon-size`, `icon-allow-overlap`,
  `text-field`, `text-font`, `text-size`, `text-anchor`, `text-offset`.
- Paint properties (closed set):
  - circle: `circle-color`, `circle-radius`, `circle-opacity`,
    `circle-stroke-color`, `circle-stroke-width`
  - raster: `raster-opacity`, `raster-fade-duration`
  - symbol: `icon-size`, `icon-color`, `icon-opacity`, `icon-translate`,
    `text-size`, `text-color`, `text-opacity`, `text-halo-color`,
    `text-halo-width`, `text-translate`
  (`icon-size`/`text-size` are layout properties in the MapLibre spec but
  are listed here once — the walker accepts them in either slot; see
  "Code-reality discrepancies".)

**Expressions** (recursive check, any depth): operators `get`, `has`,
`match`, `case`, `in`, `==`, `interpolate` (zoom input only), `literal`;
inputs may be literals, `["zoom"]`, and nested whitelisted expressions.
`["linear"]` is legal only as the interpolation of an `interpolate` over
`["zoom"]`. Standalone `"{{slug}}"` parameter token nodes are legal
wherever a value is expected (resolved/tokenized serving is unchanged).

**Explicitly out**: `feature-state`, fill / fill-extrusion / line /
heatmap layer types, SDF text layout properties (variable anchors, letter
spacing, …), pitch/terrain/sky, data-driven paint outside the whitelist
above, and every expression operator not listed.

**Evidence the whitelist suffices** (from the served styles):

- `transport-stops` is one circle layer whose `circle-color` is a `case`
  over `in`/`get` on `types`, with `interpolate`-over-zoom radius/stroke —
  fully expressible (its current document additionally carries `promoteId`
  and a default `layout.visibility`, so a subset variant is a trivial
  re-author, not a rewrite).
- `wd-huts-occupation`'s `circle-color` is a `match` on `d0_status` (the
  availability status disc) — expressible as circle paint.
- All 9 raster overlays are one raster source + one raster layer with a
  `raster-opacity` token — within the whitelist as-authored.

### D5 — Clustering is a layer-config rendering hint

Clustering is a *rendering* decision over the huts vector source; the
MapLibre spec only allows `cluster` on **geojson** sources, so putting it
in the style (even as an ignored vendor key) would break subset validity —
and the config block is already the payload's channel for renderer
metadata (`MapLayerEntry.config`, spec-scoped: it serializes from the
resolved variant row). New schema under the existing `config` JSONB:

```json
"config": { "clustering": {
  "enabled": true,
  "source": "wd-huts",
  "groupByProperty": "type_standard_slug",
  "radius": 48,
  "maxZoom": 11,
  "bubble": { "colorProperty": "type_standard_color",
              "iconProperty": "type_standard_identifier",
              "countProperty": "point_count" }
}}
```

- `groupByProperty`: only features sharing the property value cluster
  together (huts / self-catering huts / tents …). Features **lacking** the
  property form one null bucket.
- `bubble`: either property **references** — the renderer computes the
  dominant value per group client-side and derives a deterministic
  category color/icon when grouped — or **literal fallbacks**
  (`"color": "#346751"`, `"icon": "mono/accommodation.unknown"`) when no
  property should be consulted.
- **Two modes, one config**: today the client clusters on the fly
  (client-side clustering of the vector source); when clusters later come
  precomputed from the DB inside the tiles, the same properties are read
  directly from cluster features — `config` unchanged, style unchanged.
- Deliberately dropped for v0: differentiated unclustering by availability
  state (app-state dependent; a single `maxZoom: 11` covers it).

The block is validated structurally at save (known keys, types, property
names are free-form strings) and rides the huts overlay seed alongside the
existing `config.filters`.

### D6 — Validation story and one-time tagging

**Full rows — `styl` at save time (best-effort) + the hard CI gate.**
The `@maplibre/maplibre-gl-style-spec` reference validation is a Node
toolchain; the server runtime has no Node and never REQUIRES it.
`styl` (github.com/navidnabavi/styl — a Rust linter/validator/formatter
for MapLibre GL style JSON) runs as a subprocess whenever a `styl`
binary is on PATH (absent → silent skip; dev machines and the CI tests
job keep working; the style ENDPOINT never invokes it):

1. `MapLayer.clean()` — E-code violations block the save unless their
   code is on the row's `styl_ignored_rules` (JSON list of rule codes,
   e.g. `["E022"]`; `["*"]` skips styl entirely — the list subsumes a
   bool; internal validation config, never served by the API).
   W-code findings never block; they surface in the error message only
   when an E already blocks (`clean()` cannot show non-blocking
   warnings elegantly). Timeouts (~10 s), tool errors (exit 2) and
   unparsable output degrade to warnings — a styl upgrade can never
   brick a save.
2. the seed upsert — same graceful rules; the external-derived rows
   carry `styl_ignored_rules: ["*"]` (one row-level mechanism that
   eventually replaces the CI workflow's skip list, kept for now as
   defense in depth).
3. CI — the tests-job `validate_map_styles` sweep (absent binary =
   skip; W-codes always reported) and the `map-style-spec` job
   hard-gating authored full styles over the `dump_map_styles` output
   + `fixtures/styles/` with the external-derived skip list; `.stylrc`
   config committed. The style-spec release it validates against is
   what `version` records on `full` rows.

**Subset rows — pure-Python walker in the Django app.** ~100 lines in
`validation.py`: the D4 whitelists as module constants (source keys per
type, layer types, layout keys per type, paint set, expression operator
set) plus a recursive expression check; walks the document and reports
path-precise errors (`layers[2].paint.fill-color: not in subset v0.1
paint whitelist`). It runs:

- at model validation (`MapLayer.clean()`) for `profile=subset` inline
  styles — so the admin gates interactive edits,
- **directly in the seed upsert, before the write** — `map_seed` uses
  `MapLayer.objects.update_or_create(...)`, which bypasses `clean()`
  entirely, so the layer upsert calls the walker (and the
  version-required check) on the prepared defaults and fails the seed
  loudly instead of relying on the CI sweep alone,
- at seed ingest via the same path (the seed command is the ingest),
- as a CI sweep over **all** `subset`-tagged rows (management command /
  system check), catching tagging drift.

**One-time manual profile tagging** (no auto-tagging machinery): existing
rows migrate with `profile=full`; a single data update then tags the
subset-compatible rows. The current seed inventory:

| Slug | Variant(s) | Style | Tagged | Rationale |
| --- | --- | --- | --- | --- |
| `ch.swisstopo.swisstlm3d-wanderwege` | medium | raster overlay | **subset** | raster source + `raster-opacity` token — within v0.1 as-authored |
| `mtb`, `cycling`, `slopes` | medium | raster overlays (waymarked trails) | **subset** | same shape (raster + opacity token) |
| `ch.swisstopo-karto.skitouren`, `ch.swisstopo.schneeschuhwandern`, `ch.swisstopo.hangneigung-ueber_30`, `wildruhe_und_jagdbann`, `ch.bafu.alpweiden-herdenschutzhunde` | medium | raster overlays | **subset** | same shape — the 9 raster overlays in total |
| `world-topo` | high | raster fixture | **subset** | pure raster basemap (mapproxy `world_topo` facade) — subset floor for subset-only basemap ladders |
| `world-satellite-hybrid` | high | raster + vector label stack | full | vector label layers exceed v0.1; a later subset variant = the plain satellite raster (+ optional labels raster) |
| `wd-outdoor-base-mtk-hill`, `wd-outdoor-base-mtk`, `wd-outdoor-base-ofm-hill`, `mtk-outdoor` | high | vector + terrain fixtures | full | symbol/terrain stacks far outside v0.1 |
| `huts` | medium | vector (MLT) + availability, SDF symbols | full | SDF sprite text (`icon-image` with `image` expressions, variable text) exceeds v0.1 |
| `transport-stops` | medium | geojson circle | full | subset-expressible (D4 evidence); needs a trivial re-author (drop `promoteId`, default `layout.visibility`) before tagging — first non-raster subset candidate |
| `ch-swisstopo-light` | high (style_url) / low (osm raster) | external vector / osm raster | full | per the settled tagging list; the `low` osm-raster variant would pass the walker and is a later subset candidate |
| `ch-swisstopo-full` | medium | pixelkarte raster (WMTS) | full | walker-eligible, but hidden fallback — later candidate |
| `maptiler-hybrid`, `openfreemap-liberty` | high | external style_url | full | not our document; nothing to validate or tag |
| `mapy-outdoor` | high | raster fixture | full | walker-eligible, hidden reference entry — later candidate |

`version` seeding: `subset` rows get `0.1`; `full` inline rows get the
style-spec release the CI styl validation targets (e.g. `26.4.4`);
`style_url` rows stay empty.

**Follow-ups (later changes, not this one):** author subset variants for
`transport-stops` and the plain-satellite `world-satellite-hybrid`;
revisit the raster-shaped `full` rows above.

### D7 — Migration and compatibility

- One migration: adds `profile`/`version` columns (defaults `full` /
  empty), swaps `unique_slug_spec_variant` for
  `unique_slug_spec_profile_variant`, adds
  `basemaps_maplayer_profile_valid`; the data update tags the rows per D6
  (idempotent — re-running `map_seed` after the schema change converges on
  the same tags).
- Post-migration transient: inline rows carry `version=''` until the
  re-seed (D6 tagging) fills it, and `clean()` requires a `version` for
  inline styles — between the migration and the re-seed, an *edit* to
  such a row must supply `version` explicitly. One deploy step: run
  `map_seed` immediately after `migrate` (the standard release order
  already does).
- API: `?profile=` is an optional additive param on layers, layer-detail,
  style and catalog; `MapLayerEntry` gains `profile` (string, resolved
  variant) and `version` (string or null — null for `style_url` rows,
  same stance as `style_version`); `style_url` gains the `profile=…`
  query parameter for owned styles. No `Api-Version` bump (additive by
  the versioning litmus test: a pinned client's observable behavior is
  unchanged when it sends no `profile`).
- The ETag/cache-key inputs gain `profile` (D3) — new cache keys, never
  stale bodies.

## Code-reality discrepancies

Flagged where the settled session decisions assumed something the code
does not (or does differently):

1. **`version` does not exist on `MapLayer` today.** The session summary
   called it "exists but currently unused"; the only `version` fields in
   `basemaps` are `TileAssetVersion.version` (asset registry) and the
   payload's computed `style_version` cache token. This change therefore
   *adds* the field rather than repurposing one.
2. **Payload name collision: `version` vs `style_version`.** The resolved
   payload will carry both: `profile`/`version` (rules version, new) next
   to the existing `style_version` (the `?v=` immutable-cache token —
   "null for externally authored styles"). Their meanings are distinct
   and documented in the field descriptions; renaming either would break
   the additive-only constraint.
3. **Paint-vs-layout classification.** The settled paint whitelist lists
   `icon-size`/`text-size`, which the MapLibre spec classifies as *layout*
   properties. The walker accepts them in either slot (listed once, D4);
   the symbol `layout` whitelist is the minimal "sprite icon + simple
   text" set and is versioned by the subset revision.
4. **"world-satellite raster" is not a row.** The session's subset list
   names the raster basemaps "world-topo, world-satellite raster" — no
   such row exists; the satellite raster exists as the mapproxy
   `world_satellite` facade behind `world-satellite-hybrid`. Interpreted
   as: `world-topo` tagged subset now; the plain-satellite subset variant
   of `world-satellite-hybrid` is future work (D6 table).
5. **Raster-shaped rows outside the session's explicit lists.**
   `ch-swisstopo-light@low` (osm raster), `ch-swisstopo-full` (pixelkarte
   raster) and `mapy-outdoor` (raster reference) would pass the subset
   walker but stay `full` per the explicit tagging list; noted in the D6
   table as later candidates.
6. **Line references.** The session cited the `(slug, spec)` constraint
   at ~L679 and `SPEC_FALLBACKS` at ~L442 of `models.py`; at the time of
   writing they live at L718–740 (`Meta.constraints`,
   `unique_slug_spec_variant`) and L483. Names used here are the current
   ones.
7. **Cross-change sequencing.** The active `tile-asset-versioning` change
   modifies the *Caching and API contract* requirement; this change
   deliberately does not (its profile-folding lives in *Variant
   selection*, D3). Archive `tile-asset-versioning` first and merge the
   ETag input lists when this change archives.

## Risks / Trade-offs

- **Whitelist too tight** — authors hit walls (a needed operator outside
  the set). Mitigation: the subset revision is versioned (`0.2`, …);
  widening is additive (re-validate rows, bump revisions); and the escape
  hatch is always authoring a `full` row instead — no client ever breaks,
  because a subset row never displaces a full row for full-capable
  clients at the same tier.
- **Subset-only clients lose layers** — a slug without a subset variant
  disappears from their view (including every rich basemap today except
  `world-topo`). Accepted: that is the honest capability signal, and the
  frontend fallback map already handles a reduced layer set.
- **`version` vs `style_version` confusion** — two version-ish payload
  fields with different meanings. Mitigated by field descriptions and
  this document; a rename would be a breaking change for zero gain.
- **styl is an external tool pinned in CI** (`navidnabavi/styl@v0.0.4`)
  — a Rust binary outside our dependency tree validating `full` fixtures.
  Bounded blast radius: CI-only, fixture-only; serve time never depends
  on it.
- **Manual tagging drift** — a curator retags or edits a subset row into
  non-compliance. Mitigated by the CI walker sweep over all `subset` rows
  (D6); the admin `clean()` gate catches interactive edits earlier.
- **Cache-key growth** — `profile` joins the ETag inputs, multiplying
  rendered-body cache entries per layer (bounded: ≤ 2 profiles × 3 tiers).
