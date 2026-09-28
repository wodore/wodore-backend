## Context

Image delivery for hut pages aggregates three sources today: the legacy
`Hut.photo` field, curated uploads (`Image` model + associations), and six live
external providers whose results exist only in the `django_cache_persistent`
DB-cache table (TTL 7–30 d, 100k entries, culls 25% oldest). The endpoint
(`server/apps/geometries/api_images.py`) runs `asyncio.run(fetch_images_for_place(...))`
synchronously per request and sorts globally by `(-score, distance_m)`, which
discards any curation. Only the browser caches (`Cache-Control: max-age=300`).
django-q2 (3 workers) is in prod running scheduled management commands.
Full inventory: `_work/260926_image_pipeline_analysis.md` §1–2.

## Goals / Non-Goals

**Goals:**

- Hut pages never wait on external providers after a hut's first visit.
- Full manual control over external images: order, visibility, focal/crop —
  same admin surface as uploads.
- Metadata in our DB; pixels stay at the origin (imagor remains the only proxy).
- Refresh semantics: 24 h staleness for visited huts, queued in the background;
  external pressure bounded by provider TTLs, not visitor traffic.

**Non-Goals:**

- Bulk-downloading image files (localization stays an optional later rescue).
- Replacing the geokeyed provider cache (still used by nearby/map queries and
  as the sync layer beneath the 24 h pin TTL).
- Automatic classification (Phase 5, later).
- Live "fill-up" results alongside pins — pins are the truth.

## Decisions

### D1 — Pin into the existing `Image` model, file field empty

`Image` already carries everything a pin needs (`source_url_raw`, `source_ident`,
`source_org`, license, author, `image_meta`). Alternatives: a dedicated
`PinnedImage` table (duplicates schema, splits admin) or downloading files
(storage cost, license exposure, contradicts "no hosting"). Pins are
distinguishable by `provider_synced_at != null`; `image` stays empty.

### D2 — Association `order` renamed to `score`, descending position

Position = score. Initial pin writes `score = provider_score`; sync never
overwrites existing scores (manual edits survive); new pins land at their
natural position with no insertion logic. Original value kept in
`image_meta.provider_score`. Uploads default above the provider score range
(deliberate content outranks scraped). Alternative rejected: keep `order` plus
stable-insert algorithm (more machinery, two concepts for one thing).
Data is dev-only → rename is a trivial migration.

### D3 — Lazy pin-on-first-visit, no mandatory warm-up

Hut without pins → run the live pipeline in-request (same latency as today's
cold cache miss) and write pins through in the same request. Alternative
(rejected): require `geoimages_pin --all` first — one more deploy step and
huts could silently stay unpinned. The command remains for bulk prep.

### D4 — Refresh is queued, never in-request

`images_for_hut` only *enqueues* `async_task(sync_hut_images, slug)` on q2 when
`images_pinned_at` is older than 24 h, debounced per hut (cache-key lock).
The response is served from pins + response cache immediately. Layering keeps
externals cheap: pin refresh 24 h ≤ wikimedia 7 d ≤ camp2camp 30 d — daily
refreshes mostly hit the provider DB-cache; real upstream refetch happens at
provider TTL cadence.

### D5 — Response cache with stale-fallback above the pin layer

Key `(endpoint, slug, radius, sources, lang, limit)` → serialized GeoJSON in
the persistent cache, bounded TTL (~15 min) as safety, explicit invalidation on
pin sync and curation signals. On provider failure during a forced sync, serve
the last good cached response instead of partial/empty.

### D6 — Serving: pins only, in `-score, id` order

`images_for_hut` serves the hut's pins (approved + active) sorted by
`-score, id`. No live fill-up block. `sources` filter maps to pin `source_org`.
`update_cache=true` → synchronous re-pin (operator/debug escape hatch).
Legacy `Hut.photo` keeps its avatar role for now; conversion to a pin happens
in a later change.

## Risks / Trade-offs

- [Origin deletion makes a pin's imagor URL 404] → pin stays until a sync flags
  it (`review_status=pending` + admin notice); future "localize" rescue can
  persist the imagor-cached bytes into the file field.
- [Thumb URLs change (Wikimedia re-uploads)] → mutable fields refreshed by
  sync; response-cache invalidation follows.
- [First visitor per hut still eats cold latency] → identical to today's
  behavior; monthly sweep + natural traffic collapse it.
- [Score ties] → deterministic `id` tiebreaker.
- [Response cache shows stale curation briefly] → explicit invalidation on
  sync/curation writes; bounded TTL as backstop.

## Migration Plan

1. Ship response cache (independent, behavior-neutral).
2. Ship pin service + rename migration; run `geoimages_pin --hut=<sample>` on
   staging, verify hut pages against current live output.
3. Enable lazy pinning + 24 h queued refresh; observe q2 task load.
4. Rollback: feature is additive; unpinned huts simply fall back to the old
   live path (kept intact behind the same endpoint).

## Open Questions

- Default score ceiling for uploads (provider range tops out ~100 — uploads at
  200? 1000?).
- Debounce window length for the enqueue lock (proposed 15 min).
- Whether `images_for_place`/`nearby` also pin, or hut endpoints only (proposal:
  hut endpoints first).
