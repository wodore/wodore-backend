## MODIFIED Requirements

### Requirement: Caching and API contract

The layers, layer-detail, slots, style and catalog responses SHALL carry a
strong ETag and `Cache-Control: public, max-age=0, must-revalidate,
stale-if-error=604800`. The layers/slots ETag SHALL fold an exact catalog
version (max `modified` + counts over every model the payload serializes,
memoized at most 10 seconds), `lang`, `spec`, `role`, `show`, the sparse
fieldset selection and the resolved API version; rendered bodies SHALL be
cached keyed by that version (time-based page caching is removed). The
style ETag SHALL hash the response body content (not its length); the
rendered-style cache key SHALL likewise embed both the layer `modified`
timestamp and the asset-version digest (the digest is load-bearing in
the cache key; the body hash alone already covers the ETag). Served
style documents SHALL append a `?v=<version>` query parameter to
tile-server sprite URLs, the glyphs URL template, and tile URL
templates of registered versioned Martin sources. URLs that already
carry a query string or `{{double-brace}}` parameter tokens SHALL NOT be
modified; single-brace MapLibre runtime tokens (`{z}`, `{fontstack}`,
`{range}`) are part of the template and SHALL be preserved. URLs with no
published version SHALL be served unversioned.

#### Scenario: One-reload freshness

- **WHEN** a layer's `show` flag changes and an online client reloads
- **THEN** the conditional request answers non-304 with current data — no
  time window applies anywhere in the chain

#### Scenario: Version-keyed body cache

- **WHEN** any serialized model row changes
- **THEN** the catalog version changes, the previous body cache entries are
  unreachable by key, and the new body renders once

#### Scenario: Asset version change re-renders and re-keys

- **WHEN** a published asset version changes while the layer row is untouched
- **THEN** the style ETag changes, the conditional request answers non-304
  with re-rendered asset URLs, and the previous rendered body is unreachable
  by cache key

#### Scenario: Equal-length body change still busts

- **WHEN** the body changes from one version string to another of identical
  length
- **THEN** the ETag differs (content hash, not length) and clients receive
  the new body

#### Scenario: Self-rotating URLs are never double-versioned

- **WHEN** a tile URL template already contains a query string (e.g. the
  availability source's `?date={{date}}&days=4`)
- **THEN** the injector leaves it exactly as authored

## ADDED Requirements

### Requirement: Asset version registry

The system SHALL maintain a `TileAssetVersion` registry (basemaps app)
with unique keys, content-hash versions, and an origin of `martin_sync`
(published by observation) or `external` (published by verification or
manual admin edit). Tile-source versions SHALL NOT be stored; they SHALL
be computed at serve time from `max(modified)` + `count()` aggregates over
each source's declared dependency tables (including association
through-tables that the tile view joins), memoized at most 60 seconds.
The versioned-source set SHALL be an explicit opt-in registry in code;
sources without an entry SHALL never be aggregated or injected. The
initial registry contains the huts source only.

#### Scenario: Opt-in by default

- **WHEN** a style references a Martin source with no registry entry
- **THEN** its tile URLs are served without a version parameter and no
  aggregate queries run for it

#### Scenario: FK edit bumps the source version

- **WHEN** a row in any dependency table of a registered source changes
  (including in-place edits to `Category`, whose `modified` is
  trigger-maintained, and edits to association through-tables)
- **THEN** the computed version for that source changes within the memo
  window

### Requirement: Martin asset watcher publishes by observation

A recurring django-q2 task SHALL probe the sprite and glyph endpoints
that active layers actually reference (sprite entries including SDF
endpoints from authored styles; one sample glyph range per font stack
named in the styles' `text-font` arrays). Each probe SHALL carry a
per-run nonce query parameter so intermediary caches cannot serve the
watcher stale bytes. The task SHALL publish a registry entry's version
equal to the hash of the observed served bytes only when that hash
differs from the published version. Probe failure SHALL keep the stored
version. `martin_sync` SHALL enqueue one immediate watcher run after a
sync that made changes.

#### Scenario: No publication before Martin reloads

- **WHEN** sprites were synced but Martin still serves the previous bytes
- **THEN** the observed hash equals the published version and nothing is
  published (no client can cache old bytes under a new key)

#### Scenario: Publication follows the restart

- **WHEN** Martin restarts onto the new assets and the next observation runs
- **THEN** the registry version changes and subsequent style responses carry
  the new `?v=`

### Requirement: Category timestamps

`Category` SHALL carry `created`/`modified` timestamps (backfilled for
existing rows; `modified` maintained by the same PostgreSQL trigger as
other `TimeStampedModel`s, so bulk and in-place updates bump it)
displayed read-only in the admin.

#### Scenario: In-place category edit bumps dependents

- **WHEN** a category color or order is edited in place
- **THEN** both the catalog version aggregate and the huts tile-source
  version reflect the change via `max(modified)`

### Requirement: Martin cache-control for versioned sources

Registered versioned table sources SHALL be configured with a long
bounded `cache_control` (`max-age=604800`) in `tile_server/config/martin.yaml`;
function sources keep their configured values. The configuration change
SHOULD be sequenced so it only takes effect (via `martin_sync` and a
Martin restart, which follow the deploy that activates injection) after
injection is live. For function sources, an injected version parameter
flows into the function's `query_params`, rotating DB-side tile caches
together with browser and edge caches.

#### Scenario: One rotation, all layers

- **WHEN** a registered source's version changes
- **THEN** browser cache keys, edge proxy-cache keys, and the function's
  DB tile-cache key all rotate to the new version in the same style
  response

### Requirement: External asset verification

A daily django-q2 task SHALL verify external asset URLs referenced by
active layers (registered external entries) using conditional GETs with
stored validators, falling back to body hashing when no validator is
supported, and SHALL bump the registry version on a changed response.
Network failure SHALL keep the stored version. Assets not referenced by
any active layer SHALL NOT be verified.

#### Scenario: Provider updates a sprite

- **WHEN** an external sprite endpoint answers 200 with a new body on the
  daily verification
- **THEN** its registry version changes and served styles append the new
  `?v=` to that provider's URLs
