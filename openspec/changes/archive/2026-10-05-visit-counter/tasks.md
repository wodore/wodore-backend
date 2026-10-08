## 1. Counter model + write path (PR A) — shipped in #205

- [x] 1.1 `ObjectVisitDay` model (TimeStampedModel; content_type FK + object_id + GenericForeignKey, day, count; unique (content_type, object_id, day), day/count-desc index), migration
- [x] 1.2 `record_visit(obj)` (GenericFK-aware) — visitor-window dedup (ip+ua hash key, ~1 h TTL) then cache-buffer increment + threshold/first-hit flush enqueue (enqueue-only, never in-request flush)
- [x] 1.3 q2 flush task `flush_visit_counters()` — atomic read-and-clear per key, single upsert per (place, day)
- [x] 1.4 Crawler/operator guard: skip `update_cache` requests and a short static prefetch-UA list
- [x] 1.5 Hook into the **detail endpoints** (`GET /v1/huts/{slug}` and the amenity place detail) instead of `images_for_hut`/`images_for_place` as originally specced — deliberate divergence in #205: the detail fetch is the actual page-view signal, the images endpoint stays response-cacheable; tests lock the images endpoint OUT of counting
- [x] 1.6 Tests: buffer increments without DB writes in-request, visitor dedup (repeat fetch in window → single increment), flush upserts one row per (object, day) for both content types, guard skips operator/UA hits, enqueue-only behavior

## 2. Read path + consumption (PR B)

- [x] 2.1 `popular_places(limit, days=30)` helper (filters on the place content type) + tests
- [x] 2.2 Hut + GeoPlace admin: sortable visit columns — implemented as **`visits_30d` + `visits_365d`** (subquery annotations in `get_queryset`, SQL-side sorting) per maintainer decision, instead of the single `visits_7d` originally specced; `visit_window_annotation()` helper + tests

## 3. Proposed follow-ups (not implemented)

Captured for future changes; not part of this one:

- `geoimages_pin --all --popular-first`: order sweep targets by 30-day visit sum; no counters → original order (task 2.3)
- Let counters accumulate on staging; verify top places look sane (task 2.4)
- After PR A deploy: hit a few hut pages, confirm flush task created rows (admin or shell) (task 3.1)
- After PR B deploy: verify admin columns sort (note: unfold 0.87 + Django 6.1 renders no changelist — `unfold_result_list` tag predates the `InclusionAdminNode` signature change; needs an unfold upgrade before this is verifiable in the browser) (task 3.2)
