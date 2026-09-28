## 1. Counter model + write path (PR A)

- [ ] 1.1 `ObjectVisitDay` model (TimeStampedModel; content_type FK + object_id + GenericForeignKey, day, count; unique (content_type, object_id, day), day/count-desc index), migration
- [ ] 1.2 `record_visit(obj)` (GenericFK-aware) — visitor-window dedup (ip+ua hash key, ~1 h TTL) then cache-buffer increment + threshold/first-hit flush enqueue (enqueue-only, never in-request flush)
- [ ] 1.3 q2 flush task `flush_visit_counters()` — atomic read-and-clear per key, single upsert per (place, day)
- [ ] 1.4 Crawler/operator guard: skip `update_cache` requests and a short static prefetch-UA list
- [ ] 1.5 Hook into `images_for_hut` and `images_for_place` (both count via their object)
- [ ] 1.6 Tests: buffer increments without DB writes in-request, visitor dedup (repeat fetch in window → single increment), flush upserts one row per (object, day) for both content types, guard skips operator/UA hits, enqueue-only behavior

## 2. Read path + consumption (PR B)

- [ ] 2.1 `popular_places(limit, days=30)` helper (filters on the place content type) + tests
- [ ] 2.2 Hut + GeoPlace admin: sortable `visits_7d` column (subquery annotation) + tests
- [ ] 2.3 `geoimages_pin --all --popular-first`: order sweep targets by 30-day visit sum; no counters → original order; tests
- [ ] 2.4 Let counters accumulate on staging; verify top places look sane

## 3. Staging verification & rollout

- [ ] 3.1 After PR A deploy: hit a few hut pages, confirm flush task created rows (admin or shell)
- [ ] 3.2 After PR B deploy: admin column sorts, sweep ordering respects popularity in a dry-run
