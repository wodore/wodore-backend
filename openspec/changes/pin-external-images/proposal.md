## Why

Hut-page image delivery is slow and uncontrollable: external providers block
requests synchronously on cache misses, the aggregated response is recomputed on
every request, and results live only in a cullable cache table — nothing can be
reordered, hidden, focal-cropped, or classified later. Analysis:
`_work/260926_image_pipeline_analysis.md`.

## What Changes

- Server-side response cache for the geo-images endpoints (hut/place/nearby):
  serialized GeoJSON per `(slug, radius, sources, lang, limit)`, stale-fallback
  on provider errors, invalidation on pin sync and curation changes.
- External provider results are **pinned** into the existing `Image` model
  (metadata only, file field stays empty — pixels keep streaming from the origin
  through imagor):
  - Pin service: provider `ImageResult` → `Image` rows, deduped by
    `(source_org, source_ident)`, mutable fields refreshed on re-sync.
  - Hut image association: **rename `order` → `score`**, descending position;
    new pins get their provider score, existing scores are never overwritten by
    sync (manual curation survives); original score kept in
    `image_meta.provider_score`.
  - Lazy pin-on-first-visit: huts without pins run the live pipeline once and
    write results through in the same request — no warm-up required.
  - Visitor-triggered refresh: requests only *enqueue* a q2 background task
    when pins are older than 24 h (never in-request work); external pressure
    stays bounded by provider-layer TTLs (7 d Wikimedia / 30 d camp2camp).
  - `geoimages_pin` management command (`--all` / `--hut=slug` / `--dry-run`)
    as an operator convenience; monthly q2 hygiene sweep for rarely visited huts.
- Hot path after pinning: DB + response cache only — no provider calls, no
  redirect HEADs (resolved thumb URLs are stored).

## Capabilities

### New Capabilities

- `image-response-cache`: Server-side caching of aggregated image endpoint
  responses with stale-fallback and invalidation rules.
- `external-image-pinning`: Materializing external provider results as pinned
  `Image` rows with score-based ordering, lazy first-visit pinning, and
  queued background refresh.

### Modified Capabilities

(none — no existing spec covers image delivery)

## Impact

- **Code**: `server/apps/geometries/api_images.py` (response cache, pin
  fast-path), `server/apps/geometries/providers/base.py` + `wodore.py`
  (pin mapping, score-based serving), new pin service module, hut/geoplace
  association models (rename `order` → `score`, migration; dev-only data),
  new management command, q2 task.
- **API**: `/v1/geo/images/*` behavior-compatible; `update_cache=true` becomes
  "force pin sync". Response content/ordering changes (curated score order).
- **Dependencies**: django-q2 (already in prod), imagor unchanged.
- **Ops**: one new scheduled q2 task (monthly sweep); no new infrastructure.
