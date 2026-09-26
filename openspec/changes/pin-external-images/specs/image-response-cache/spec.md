## ADDED Requirements

### Requirement: Server-side response caching for image endpoints
The geo-images endpoints (`hut`, `place`, `nearby`) SHALL cache the serialized
response per `(endpoint, slug-or-center, radius, sources, lang, limit)` in the
persistent cache backend.

#### Scenario: Repeat request served from cache

- **WHEN** two identical requests hit `GET /v1/geo/images/hut/{slug}` within the cache TTL
- **THEN** the second response is served from the response cache without recomputing aggregation, sorting, or URL generation

#### Scenario: Different parameters use different cache entries

- **WHEN** the same hut is requested with different `lang`, `radius`, `sources`, or `limit`
- **THEN** each parameter combination is cached and served under its own key

### Requirement: Stale-fallback on provider failure
The endpoint SHALL serve the last good cached response for a key when a forced
refresh (`update_cache=true`) or a lazy pin run fails, instead of returning an
empty or partial result, if such a cached response exists.

#### Scenario: Forced sync failure falls back

- **WHEN** a request with `update_cache=true` is issued and the provider pipeline raises
- **THEN** the endpoint responds with the previously cached response (if any) rather than an error or empty feature list

### Requirement: Cache invalidation on data changes
The response cache for a hut's image endpoints SHALL be invalidated when the
hut's pins change (sync completion, manual curation, pin visibility changes).

#### Scenario: Pin sync invalidates

- **WHEN** a background or forced pin sync completes for a hut
- **THEN** subsequent requests for that hut recompute and re-cache the response from the updated pins

### Requirement: Bounded cache lifetime
Cached responses SHALL carry a maximum TTL (configurable, default ≤ 15 minutes)
as a safety net against missed invalidations.

#### Scenario: Entry expires

- **WHEN** a cached response is older than the configured maximum TTL
- **THEN** the next request recomputes it instead of serving the stale entry
