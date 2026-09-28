## Context

Hut/place pages are served by the frontend, which fetches hut details and
images from the API (`/v1/huts/…`, `/v1/geo/images/hut/{slug}`). We control
both sides, so the cheapest reliable counting point is the backend API
itself. django-q2 runs in prod; the persistent cache (DatabaseCache) is
available for batching. Hut uses integer PKs, GeoPlace too — a shared
counter table with `(place_type, place_id, day)` is simple and indexed.

## Goals / Non-Goals

**Goals:**

- Count detail views per place per day, best-effort, without adding
  latency or failure modes to the observed request
- Expose popularity to admin and to the image sweep (`--popular-first`)
- Tiny table: one row per (place, day); counters aggregate on write, not
  per hit

**Non-Goals:**

- Unique/verified visitor metrics, sessions, bots filtering beyond a
  minimal crawler guard
- Public API exposure of counts
- Ranking changes in the image response (future change)

## Decisions

### D1 — Count in the hut/place detail API, not middleware

The hut detail endpoint (`/v1/huts/{slug}`) and the images-for-place/hut
endpoints are the canonical "someone looked at this place" signals.
Counting there (not in global middleware) keeps the surface explicit,
skips admin/map-tile/autocomplete traffic for free, and gives us the slug
without URL parsing. Images-for-hut is the strongest signal (every hut
page fetches it) — count on that endpoint only, once per request, skipping
`update_cache` (operator) requests.

### D2 — Cache-batched async flush, never a row lock in the request

Increment in the request = `INSERT … ON CONFLICT DO UPDATE count += 1` —
correct but adds a write to the hot path. Instead: bump a per-(place, day)
counter in the **default cache** (locmem per worker — merges are
acceptable; best-effort), and enqueue a single q2 flush task when a
counter crosses a small threshold (e.g. every 10 hits) or on first hit of
a place. The flush task reads-and-clears the cache keys and upserts the
DB rows. Lost counts on worker restart are acceptable (±single digits).

Alternative rejected: synchronous upsert per request — a write on every
hut-page hit, hot-row contention on popular places.

### D3 — One polymorphic counter table

`PlaceVisitDay(place_type: 'hut'|'geoplace', place_id: int, day: date,
count: int)` with unique `(place_type, place_id, day)` and an index on
`(day, -count)` for "top today" style queries. No FKs (places can be
deleted; counters outlive them harmlessly) — `place_type` + `place_id`
with a helper resolving slugs. A `total` convenience column is derived
(sum query) rather than stored, to avoid a second hot row.

### D4 — Admin + sweep consumption

- Hut/GeoPlace admin: `visits_7d` sortable column (sum of last 7 days,
  subquery annotation)
- `geoimages_pin --all --popular-first`: orders the sweep targets by
  30-day visit sum (descending) so a truncated sweep window refreshes
  what matters
- `popular_places(limit, days=30)` helper in the counter module for future
  consumers (frontend "popular huts" section, ranking, classification
  priority)

### D5 — Crawler guard, minimal

Skip counting when the request has no `Accept: text/html`-ish browser
marker? Too clever. Simply: skip `update_cache` requests and skip
unauthenticated prefetch user agents matching a short static list
(python-requests, curl, wget, headless). Good enough for a popularity
signal; documented as approximate.

## Risks / Trade-offs

- [Locmem counters lost on restart] → acceptable: best-effort signal, not
  billing; flush threshold small
- [Popular place row contention during flush] → single upsert per flush
  batch, not per hit; fine at our scale
- [Counter inflation from broken clients retrying] → acceptable noise;
  daily aggregation smooths spikes

## Migration Plan

1. Merge model + counting + flush task (no behavior change elsewhere)
2. Let counters accumulate a few days
3. Merge admin column + `--popular-first` (safe, additive)

## Open Questions

- Count `/place/{slug}` images endpoint too, or hut only for now?
  (proposal: hut only — geoplace pages barely exist in the frontend yet)
- Flush threshold (10?) and whether the monthly sweep should default to
  `--popular-first` once data exists
