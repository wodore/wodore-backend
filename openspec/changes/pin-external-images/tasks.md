## 1. Response cache (PR A — independent, behavior-neutral)

- [x] 1.1 Add response-cache helper: key builder `(endpoint, slug, radius, sources, lang, limit)`, get/set wrappers over the persistent cache, configurable max TTL (default 15 min)
- [x] 1.2 Wire caching into `images_for_hut`, `images_for_place`, `nearby_images` in `server/apps/geometries/api_images.py`
- [x] 1.3 Implement stale-fallback: on provider failure return last good cached response if present
- [x] 1.4 Add cache invalidation hook callable from pin sync and curation signals
- [x] 1.5 Tests: cache hit path, parameter separation, stale fallback, TTL expiry, invalidation

## 2. Data model groundwork (PR B — start)

- [ ] 2.1 Rename association `order` → `score` on hut and geoplace image associations (migration; dev-only data) with descending ordering + `id` tiebreaker
- [ ] 2.2 Add `Image.provider_synced_at` (datetime, null = not a pin) and per-hut `images_pinned_at` marker (migration)
- [ ] 2.3 Default score for uploaded images above provider range (admin wiring), preserve original provider score in `image_meta.provider_score`

## 3. Pin service (PR B)

- [ ] 3.1 Implement `pin_hut_images(hut, image_results)`: `get_or_create` by `(source_org, source_ident)`, update mutable fields, attach with `score = provider_score` (never overwrite existing), stamp `provider_synced_at`/`images_pinned_at`
- [ ] 3.2 Map `ImageResult` → `Image` fields (URLs, license, author, attribution, dimensions, capture date, captions)
- [ ] 3.3 Dead-origin flagging: sync marks pins whose origin disappeared for review (no auto-delete)
- [ ] 3.4 Tests: dedupe across syncs, mutable-field refresh, score semantics (new pin placement, manual curation survives), visibility filtering

## 4. Endpoint serving (PR B)

- [ ] 4.1 `images_for_hut` fast path: pins exist → serve approved+active pins sorted by `-score, id`; no provider calls
- [ ] 4.2 Lazy pin-on-first-visit: no pins → live pipeline, write-through, serve same results
- [ ] 4.3 `sources` filter maps to pin `source_org`; `update_cache=true` → forced synchronous re-pin
- [ ] 4.4 Invalidate response cache on pin writes (sync completion, curation changes)
- [ ] 4.5 Tests: fast-path isolation (no provider module touched), lazy write-through, forced sync, hidden-pin exclusion

## 5. Background refresh + command (PR C)

- [ ] 5.1 q2 task `sync_hut_images(slug)` running providers → pin service → cache invalidation
- [ ] 5.2 Enqueue-only refresh in `images_for_hut` when pins older than 24 h, debounced per hut (cache-key lock)
- [ ] 5.3 Management command `geoimages_pin` with `--all`, `--hut=<slug>`, `--dry-run` (django-admin-runner registration)
- [ ] 5.4 Monthly q2 Schedule for the hygiene sweep (rarely visited huts)
- [ ] 5.5 Tests: enqueue conditions (24 h boundary, debounce), task execution, command modes

## 6. Staging verification & rollout

- [ ] 6.1 Run `geoimages_pin --hut=<sample huts>` on staging; diff hut-page output vs pre-change live results
- [ ] 6.2 Verify hot path makes zero provider calls (logs) after pinning; verify first-visit lazy path on an unpinned hut
- [ ] 6.3 Verify 24 h refresh enqueue + q2 task run; confirm external request counts stay at provider-TTL cadence
- [ ] 6.4 Admin check: reorder (edit score), hide, focal/crop on a pinned external image reflected on staging
