## Why

Popularity drives several planned features — image warm-up priority, cache
refresh ordering, later content ranking — but we have no signal for which
huts/places visitors actually look at. The image pipeline currently treats
every place equally (lazy first-visit pinning, 24 h refresh, monthly sweep).

## What Changes

- A lightweight per-place visit counter, incremented on **detail views**
  (hut/place pages — the frontend's per-hut data fetches), aggregated daily
  per place so the table stays tiny regardless of traffic.
- Counters are best-effort: counting must never slow down or break the
  request it observes (async write path, no unique constraints that can
  raise).
- Popularity surfaces in the admin (sortable column on Hut/GeoPlace) and as
  an internal signal — no public API exposure in this change.
- The image sync command (`geoimages_pin --all`) gains `--popular-first`
  ordering so the sweep refreshes busy places first when the window is
  short.

## Capabilities

### New Capabilities

- `place-visit-counter`: Best-effort, aggregated visit counting for huts
  and GeoPlaces with async writes, daily aggregation, and admin/sweep
  consumption.

### Modified Capabilities

(none — no existing spec covers visit tracking; image-pipeline consumption
is additive and doesn't change `external-image-pinning` requirements)

## Impact

- **New model**: `ObjectVisitDay` generic daily counter (content_type +
  object_id via Django contenttypes / GenericForeignKey, day, count) in a
  small app or `geometries`
- **Write path**: endpoint hook on the place/hut images requests →
  visitor-window dedup (ip+ua hash, cache-only) then cache-buffered async
  increment, never in the request path
- **Read path**: admin column + `geoimages_pin` ordering; internal helper
  `popular_places(limit)` for future consumers
- **Dependencies**: django-q2 (already in prod); no new infrastructure
- **Privacy**: counts only — no IPs, no user agents, no session data
