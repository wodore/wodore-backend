## Context

Place (and, until the hut→place migration lands, hut) pages are served by
the frontend, which fetches images from the API (`/v1/geo/images/place/…`,
`/v1/geo/images/hut/…`). We control both sides, so the cheapest reliable
counting point is the backend API itself. django-q2 runs in prod; the
default cache is available for batching and visitor dedup. Places are the
strategic model (huts migrate into them eventually), and other models may
want counting later — the counter therefore attaches via Django's
contenttypes framework (GenericForeignKey) instead of a hand-rolled
place_type enum.

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

### D1 — Count in the images endpoints, place-first, not middleware

> **Shipped differently (#205):** counting hooks into the **detail
> endpoints** (`GET /v1/huts/{slug}` and the amenity place detail), not
> the images endpoints. The detail fetch is the actual page-view signal,
> and keeping the images endpoints uncounted preserves their response
> cacheability (tests lock this in). The `update_cache`/UA guard stayed.

The images endpoints are the canonical "someone looked at this place"
signals — every place/hut page fetches them. Counting there (not in global
middleware) keeps the surface explicit, skips admin/map-tile/autocomplete
traffic for free, and gives us the object without URL parsing. Count on
`images_for_place` and `images_for_hut` alike (huts become places at the
migration; until then they are simply a second content type), skipping
`update_cache` (operator) requests.

### D2 — Visitor-window dedup + cache-batched async flush, no writes in the request

One request per fetch would inflate counts (gallery refetches,
back-navigation, retries). Before buffering, dedup per visitor: derive an
opaque key from `hash(ip + user_agent)` and mark
`(visitor, content_type, object_id)` in the **default cache** with a ~1 h
TTL — only the first hit in the window buffers an increment. No cookies
(a `Set-Cookie` from the images endpoint would defeat the response
cache), no PII stored, NAT/proxy merging acceptable for a popularity
signal.

Buffered increments then live in a per-(object, day) cache counter and a
single q2 flush task is enqueued when a counter crosses a small threshold
(e.g. every 10 hits) or on the object's first buffered visit. The flush
task reads-and-clears the keys and upserts the DB rows. Lost counts on
worker restart are acceptable (±single digits).

Alternative rejected: synchronous upsert per request — a write on every
hut-page hit, hot-row contention on popular places.

### D3 — Generic counter table via contenttypes

`ObjectVisitDay(content_type: FK[ContentType], object_id: int, day: date,
count: int)` with a `GenericForeignKey` and unique
`(content_type, object_id, day)`, plus an index on `(day, -count)` for
top-N-per-day queries. This is Django's built-in mechanism for
"belongs to any model" — places today, huts until the hut→place
migration (which rewrites `content_type` in a data migration), and
avails/orgs later without schema changes. No hard FKs to the counted
models (counters outlive their objects); helpers resolve
`popular_places` by filtering on the place content type. The model uses
the project's TimeStampedModel — `created`/`modified` reflect first/last
flush of a day's row, useful for debugging, not analytics.

### D4 — Admin + sweep consumption

> **Shipped (admin columns):** instead of a single `visits_7d` column,
> the admins show sortable `visits_30d` + `visits_365d` (maintainer
> decision) via `visit_window_annotation()` subquery annotations. The
> `--popular-first` sweep flag is proposed follow-up work (see tasks.md).

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
- [Counter inflation from broken clients retrying] → dampened by the
  visitor-window dedup; daily aggregation smooths the rest
- [IP-hash dedup merges users behind NAT] → acceptable: approximate
  popularity signal, not analytics

## Migration Plan

1. Merge model + counting + flush task (no behavior change elsewhere)
2. Let counters accumulate a few days
3. Merge admin column + `--popular-first` (safe, additive)

## Open Questions

- Count `/place/{slug}` images endpoint too, or hut only for now?
  (proposal: hut only — geoplace pages barely exist in the frontend yet)
- Flush threshold (10?) and whether the monthly sweep should default to
  `--popular-first` once data exists
