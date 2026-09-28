# Image Pipeline — Status Analysis & Improvement Plan

2026-09-26 · backend main checkout (read-only analysis, no code changed)

## 1. Current architecture (as found)

### Source 1 — old single photo field

- `Hut.photo` + `Hut.photo_attribution` (`server/apps/huts/schemas/_hut.py`, model in
  `server/apps/huts/models/_hut.py`), filled by the hut import (`huts` command,
  `include=location,photos,photos_attribution`) — value is a **media-relative path**
  to a file downloaded at import time (refuges.info).

- Consumed in `server/apps/huts/api/_hut.py`: `avatar = media_url + hut.photo` and
  prepended as first gallery item (`hut_db.images = [old_photo, *images]`).

- Admin still shows it (`huts/admin/_hut.py`, "old style").

### Source 2 — photos app (local, curated)

- `Image` model (`server/apps/images/models.py`): file field (Django media storage),
  `image_meta` (focal/crop, width/height), license FK, author/attribution, captions,
  `review_status`, `source_url`/`source_url_raw`/`source_ident`/`source_org`,
  tags (`ImageTag` incl. color), capture/upload metadata.

- Linked to places via association models with **`order` field**
  (`server/apps/geometries/models/_associations.py`: "Display order for this link",
  `ordering = ["order", "id"]`, index `(geo_place, order)`); huts via
  `hut.image_set` (reverse FK).

- Imported rows are created by `Image.xxx_from_schema(...)` during hut import
  (`server/apps/huts/models/_hut.py` → `server/apps/images/forms.py`) —
  **this is the existing "download from external" mechanism** (refuges.info photos).

- Served through `WodoreProvider` (`providers/wodore.py`): DB query only (fast),
  `score=50` hardcoded, focal/crop extracted from `image_meta`,
  **`url_large = img.source_url_raw or str(img.image)`** — i.e. for imported rows
  with a `source_url_raw` it still points imagor at the *external* URL even though
  the file sits in local media storage.

### Source 3 — live external providers

- Registry (`providers/__init__.py`): camptocamp, mapillary, panoramax,
  refugesinfo, wikimedia_commons, wodore. (Flickr removed.)

- Endpoint `GET /geo/images/hut/{slug}` (`server/apps/geometries/api_images.py`,
  `images_for_hut`): **runs `asyncio.run(fetch_images_for_place(...))` synchronously
  in the request**; providers run in parallel (`asyncio.gather`, base.py:1590).

- Sort: `results.sort(key=lambda r: (-r.score, r.distance_m))` → limit →
  `post_process_images` (imagor URL construction, orientation split,
  GeoJSON features; variants avatar/thumb/preview/medium/large ×
  landscape/portrait).

### Caching map (answers "where is it cached?")

| Layer | Backend | TTL | Notes |
| --- | --- | --- |---|
| Provider *metadata* results | `django_cache_persistent` **DB table** (`caches["persistent"]`, settings `components/caches.py`) | wikimedia 7 d (`n_ttl`), camptocamp 30 d | key `geoimages:{provider}:{lat}:{lon}:{radius}:{precision}` (coords rounded by `PRECISION_LEVELS`); `MAX_ENTRIES=100k`, culls 25 % oldest when full |
| Endpoint *response* | **none server-side** | — | recomputed every request: DB-cache reads + WodoreProvider queries + sort + URL building; only `Cache-Control: max-age=300` (browser) |
| Commons redirect resolution | `get_redirect_url` HEAD, `@file_cache` 30 d (`images/transfomer.py`) | 30 d | first request for a commons `Special:Redirect` URL blocks on a HEAD to Wikimedia |
| provider_info / license lookups | `default` cache = **LocMem**, 5 min/1000 entries, per-process | 30 min per entry | near-useless with multiple workers; harmless |
| Imagor source + result | **disk** (`media/imagor_data/{storage,result}`, docker-compose imagor: `FILE_STORAGE_BASE_DIR`, `FILE_RESULT_STORAGE_BASE_DIR`) | **no TTL** — forever until pruned | `AUTO_WEBP/AVIF`, `RESULT_STORAGE_PATH_STYLE=size`, image `shumc/imagor:latest` (upgrade 1.6.7→1.9.6 pending) |
| Imagor "cache" of the *aggregated answer* | n/a | n/a | doesn't exist |

### Task infrastructure (exists, unused for images)

- **django-q2** qcluster (`Q_CLUSTER`, `settings/components/common.py`: 3 workers,
  timeout 24 h, `catch_up=False`, recycle 5) + `django-admin-runner`
  (`register_command`) — precedent: `update_availability` (hours-long,
  `--all`/`--hut-slug`/`--dry-run`).

## 2. Problems (confirmed in code)

1. **Slow responses**: cold cache-miss requests block synchronously on external
   APIs (wikidata SPARQL + commons API chains are the worst); warm requests still
   recompute aggregation + sort + URL building every time; first hit per commons
   URL adds a blocking HEAD (`get_redirect_url`).
2. **No server-side response cache** — only the browser's 5 min.
3. **429s at imagor**: bursts of on-demand upstream fetches when a hut page with
   unseen images goes viral / gets crawled; imagor upgrades (timeouts, version)
   still pending.
4. **No control over selection/order**: endpoint sorts purely by
   `(-score, distance_m)`; association `order` and `review_status` of curated rows
   are effectively the only levers, and ordering is ignored by the final sort.
   No focal/crop for external images (post_process falls back to `"smart"`).
5. **External results are ephemeral**: they live in a cullable DB-cache table, not
   in the domain model — nothing to curate, nothing to classify later.
6. **Inconsistency**: imported refuges.info rows keep serving from
   `source_url_raw` (external) although the file is in local media.

## 3. Recommendation (phased, keeps hosting burden ≈ zero)

Guiding principles: **metadata in our DB, pixels stay at the origin, imagor is the
only proxy.** No bulk image downloads; downloads remain the exception (existing
refuges.info import path, org uploads).

### Phase 1 — make the hot path fast (small, high leverage)

- **Server-side response cache** for `images_for_hut`/`images_for_place`/nearby:
  key `(slug, radius, sources, lang, limit)` → serialized GeoJSON in the
  persistent cache, TTL e.g. 60 min, **stale-fallback** on provider errors
  (serve last good instead of partial/empty).

- Invalidate (or short-TTL) when the warm-up or admin curation writes.
- Effect: warm hut pages = 1 DB read, no asyncio.run, no sorting.

### Phase 2 — warm the provider metadata cache (fixes "slow external")

- New command `geoimages_warm` (q2 `Schedule`, nightly, `catch_up=False`):
  iterate public huts in priority order, call the providers with the **same cache
  keys** the endpoint uses (`update_cache=False`, but write-through with fresh
  TTL), paced (e.g. 1 hut / 2 s per provider, token bucket per host; Wikimedia
  etiquette: serial, proper UA).

- Refresh semantics = the 7 d/30 d TTLs never lapse for popular huts; first-visitor
  penalty moves to the night job.

- Load: ~N huts × 3–6 provider calls/night; can be spread over the week
  (priority huts daily, rest weekly).

- Bonus: fold the redirect-HEAD pre-resolution (`get_redirect_url`) into the warm
  job so no request ever blocks on it.

### Phase 3 — pin external results into the `Image` model (fixes control)

- Keep the **same `Image` model** — it already has everything: license, author,
  `source_url_raw` (the large servable thumb), `image_meta` (focal/crop/dims),
  `review_status` (show/hide), tags (later classification), association `order`.
  `image` file field simply stays empty for pins → **we host nothing new**.

- Sync command / admin action: take current provider results for a hut →
  `get_or_create` Image rows (dedupe on `source_ident`), attach to the hut with
  `order` from score/distance. WodoreProvider then serves curated rows first
  **in association order** (curated block, then live "fill-up" results only if the
  hut has fewer than K images).

- Admin gains: reorder, hide, set focal/crop on external images — same UI as
  local photos (Unfold tab already exists).

- Old `Hut.photo`: stop prepending; convert to a pinned Image at next import,
  keep as avatar fallback only.

- Fix while here: prefer the local file over `source_url_raw` for rows that
  actually have one (imported refuges.info photos).

- Stale pins: nightly prune/re-sync (origin 404s → flag `review_status=pending`,
  don't hard-delete).

### Phase 4 — warm imagor for the images that matter

- After Phase 2/3, for each hut's top-K pinned images (K≈6): issue server-side
  GETs to the **preview** and **medium** imagor URLs (the variants the hut page
  actually renders first). 2 GETs × 6 images × N huts per night, spread out —
  this is exactly the traffic that otherwise bursts as 429s on first visit.

- Result cache has no TTL → one GET warms a variant "forever"; add a small disk
  usage check to the job log for prune planning.

- Note: with `AUTO_WEBP` browsers negotiate derived encodes from the cached
  source — cheap either way.

### Phase 5 (later) — classification

- Runs on pinned images only (stable identity), pulling pixels **from our own
  imagor** (thumb URL), never from the origin. Writes tags
  (`winter/summer/inside/outside/hut…`) + suggested focal into `image_meta`,
  `review_status=pending` for admin confirmation. The Image model needs no
  changes — tags + meta already exist.

## 4. What we deliberately do NOT do

- **Bulk-download originals** — re-hosting costs (storage, bandwidth, license
  exposure) for pixels imagor can stream from origin; contradicts "ideally no
  hosting".

- Replace the provider cache with the Image table — live search (map-based
  nearby queries at arbitrary coordinates) still needs the geokeyed cache; pins
  are the *curation* layer on top for hut pages.

## 5. Open questions

- Hut count for warm-up sizing (public/is_public) — measure before choosing pace.
- Which variants does the frontend actually request first? (frontend audit;
  warm only those in Phase 4.)

- Priority metric for huts (existing availability priority? view counts?).

## 6. Phase 3 detailed design (adopted 2026-09-26 after discussion)

Refresh model: **stale-while-revalidate per hut** — initial full pin sync, then a
30-day TTL refreshed by visitor traffic (visited huts stay fresh, unvisited huts
cost nothing). Phase 1 (response cache) ships alongside.

### Data model — reuse `Image`, no new table

- `image` file field stays **empty** for pins (we host nothing).
- `source_url_raw` = large servable thumb URL; `source_url` = provenance page.
- `source_ident` = stable dedupe key (`wikicommons:File:X.jpg`, `camptocamp:123`).
- `source_org` FK = provider identity (WodoreProvider already maps it to the
  provider slug).
- `image_meta` (width/height/focal/crop), license, author, capture_date, captions:
  all exist.
- **New fields (migration)**: `provider_synced_at` (datetime, null = not a pin)
  and a hut-level `images_pinned_at` marker (on Hut or a small per-hut row) to
  drive the 30-day TTL cheaply.
- Hut association: **rename `order` → `score`** (images still dev-only, rename
  is cheap). Position = score, descending (`ordering = ["-score", "id"]`).
  Initial sync writes the provider score into it; manual curation = edit the
  number (or admin drag = renumber). The **original provider score is kept in
  `image_meta.provider_score`** for reference/reset. Sync **never overwrites**
  an existing association's score — only new pins get theirs set, which lands
  them at their natural position with zero insertion logic. Uploaded/curated
  photos get a default score above the provider range (they are deliberate
  content), user-editable.

### Sync flow

1. **Initial/lazy**: management command `geoimages_pin [--all|--hut=slug|--dry-run]`
   (schedulable via q2, **monthly hygiene sweep** for rarely visited huts —
   they also self-pin on first visit): run providers → map `ImageResult` →
   `Image` rows (get_or_create on `(source_org, source_ident)`, update mutable
   fields — thumb URLs change on Wikimedia re-uploads) → attach to hut with
   `score = provider_score` → `provider_synced_at = now()`.
2. **Runtime refresh (24 h, queued — never in-request)**: `images_for_hut`
   only *enqueues* when `images_pinned_at` is older than **24 h** —
   `async_task(sync_hut_images, slug)` onto the **q2 cluster**; the response
   itself is served immediately from pins/response cache and never waits for
   providers. The background task runs the providers, updates/adds pins, and
   resets `images_pinned_at` (debounced: one task per hut per TTL window,
   regardless of visitor bursts). External pressure stays bounded by the
   **provider-layer TTLs**, not by the pin TTL: a daily refresh of a 7-day
   Wikimedia cache is 6 cheap DB-cache reads + 1 real refetch — the layers
   stack (24 h pins ≤ 7 d wikimedia ≤ 30 d camp2camp).
3. **Pruning**: images gone from provider results keep their pins (human may have
   curated) but re-verification marks dead origins; a later "localize" action can
   download the imagor-cached copy into the file field as a rescue.
4. **New images found during refresh**: auto-approved with
   `association.score = provider_score` → natural position without moving any
   existing pin. Recency is already inside the provider score ("newer is
   better" lands for free). Original score persisted in
   `image_meta.provider_score` (no migration — JSON field).
5. **Lazy pin-on-first-visit (no warm-up required)**:
   pins exist? → serve from DB (+ response cache)
   no pins?  → run the live pipeline (today's code path, same latency as a
               today's cold cache miss), pin the results in the same request
               (write-through), return them. Next request hits the fast path.
   `update_cache=true` → force the sync path. The bulk warm-up command remains
   as an operator convenience (`--all`, `--hut=slug`, `--dry-run`).

### Serving order (fixes "no control")

Pins are the truth — no live fill-up block. `images_for_hut` serves the hut's
pins **sorted by `-score, id`** on the association (initial score = provider
score; manual edits always survive syncs, see sync flow §4).
Live providers run only inside the sync paths (background 30 d refresh or
lazy first visit), never on the plain hot path. Admin hiding all pins =
empty gallery, by design. `sources` filtering maps to pin `source_org`.
Response cache invalidated on sync completion and curation changes
(plus bounded TTL as safety).

### When do we still hit external servers?

| Trigger | Frequency | What |
| --- | --- | --- |
| Pin sync (initial / 30 d / manual) | ≤ 1× per 30 d per **visited** hut | provider metadata APIs (SPARQL, Commons API, camp2camp) |
| Imagor origin fetch | once per variant URL ever (imagor disk cache has no TTL) | image bytes |
| Redirect HEAD (Commons) | never for pins — resolved URLs are stored | — |
| Live fill-up (pins < K) | per request, provider-cached (7–30 d) | metadata only |
| Hot path after pinning | **never** | DB + response cache only |

### Escape hatch (user's point)

Because `source_url_raw` is a stable DB field, a later "download this image"
(admin action or bulk job) is trivial: pull it through imagor (bytes usually
already cached on our disk) into the file field → the pin survives origin
deletion. Not in v1, but the design keeps the door open.

### Implementation order

- **PR A (Phase 1)**: endpoint response cache + stale fallback.
- **PR B (Phase 3 core)**: pin service + sync command + ordering fix +
  hut association wiring; initial sync run on staging.
- **PR C (Phase 3 runtime)**: visitor-triggered 30 d refresh via q2 + old
  `Hut.photo` conversion + dead-origin flagging.
