## 1. Response cache (PR A — independent, behavior-neutral)

- [x] 1.1 Add response-cache helper: key builder `(endpoint, slug, radius, sources, lang, limit)`, get/set wrappers over the persistent cache, configurable max TTL (default 15 min)
- [x] 1.2 Wire caching into `images_for_hut`, `images_for_place`, `nearby_images` in `server/apps/geometries/api_images.py`
- [x] 1.3 Implement stale-fallback: on provider failure return last good cached response if present
- [x] 1.4 Add cache invalidation hook callable from pin sync and curation signals
- [x] 1.5 Tests: cache hit path, parameter separation, stale fallback, TTL expiry, invalidation

## 2. Data model groundwork (PR B — start)

- [x] 2.1 Rename association `order` → `score` on hut and geoplace image associations (migration; dev-only data) with descending ordering + `id` tiebreaker
- [x] 2.2 Add `Image.provider_synced_at` (datetime, null = not a pin) and per-hut `images_pinned_at` marker (migration)
- [x] 2.3 Default score for uploaded images above provider range (admin wiring), preserve original provider score in `image_meta.provider_score`

## 3. Pin service (PR B)

- [x] 3.1 Implement `pin_hut_images(hut, image_results)`: `get_or_create` by `(source_org, source_ident)`, update mutable fields, attach with `score = provider_score` (never overwrite existing), stamp `provider_synced_at`/`images_pinned_at`
- [x] 3.2 Map `ImageResult` → `Image` fields (URLs, license, author, attribution, dimensions, capture date, captions)
- [x] 3.3 Dead-origin flagging: sync marks pins whose origin disappeared for review (no auto-delete)
- [x] 3.4 Tests: dedupe across syncs, mutable-field refresh, score semantics (new pin placement, manual curation survives), visibility filtering

## 4. Endpoint serving (PR B)

- [x] 4.1 `images_for_hut` fast path: pins exist → serve approved+active pins sorted by `-score, id`; no provider calls
- [x] 4.2 Lazy pin-on-first-visit: no pins → live pipeline, write-through, serve same results
- [x] 4.3 `sources` filter maps to pin `source_org`; `update_cache=true` → forced synchronous re-pin
- [x] 4.4 Invalidate response cache on pin writes (sync completion, curation changes)
- [x] 4.5 Tests: fast-path isolation (no provider module touched), lazy write-through, forced sync, hidden-pin exclusion

## 5. Background refresh + command (PR C — place-generic: huts and geoplaces)

- [x] 5.1 q2 task `sync_place_images_task(place_type, slug)` running providers → pin service → cache invalidation, for huts and geoplaces
- [x] 5.2 Enqueue-only refresh in `images_for_hut` and `images_for_place` when pins older than 24 h, debounced per place (cache-key lock)
- [x] 5.3 Management command `geoimages_pin` with `--all`, `--place=<slug> --type={hut,geoplace,all}`, `--dry-run`, `--check-origins` (django-admin-runner registration)
- [x] 5.4 Monthly q2 Schedule for the hygiene sweep (rarely visited places; created via the Schedule admin)
- [x] 5.5 Dead-origin flagging: pins missing from fresh results with dead origins (HEAD 404/410) move to review — no auto-delete
- [x] 5.6 Tests: enqueue conditions (24 h boundary, debounce), task execution for both place types, command modes, dead-origin flagging

## 6. Staging verification & rollout

- [ ] 6.1 Run `geoimages_pin --hut=<sample huts>` on staging; diff hut-page output vs pre-change live results
- [ ] 6.2 Verify hot path makes zero provider calls (logs) after pinning; verify first-visit lazy path on an unpinned hut
- [ ] 6.3 Verify 24 h refresh enqueue + q2 task run; confirm external request counts stay at provider-TTL cadence
- [ ] 6.4 Admin check: reorder (edit score), hide, focal/crop on a pinned external image reflected on staging
