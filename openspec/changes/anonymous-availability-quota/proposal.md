## Why

Rate throttling (the `api-throttling` change) caps request *rate* but not
*volume*: a scraper pacing itself under the daily cap still harvests
everything, while IP-keyed limits penalize shared NATs (school, company,
mobile carrier) and barely slow a distributed scraper. The availability data
is the API's highest-value asset; the product intent is freemium — casual
anonymous use stays free, heavy use asks for a login.

## What Changes

- **Anonymous quota on the availability endpoints**: N requests free per
  window (default 20/day; weekly window supported), then HTTP 429 with error
  code `anonymous_quota_exceeded` — the frontend turns that into a login
  prompt, not a dead end.
- **Quota identity = visitor fingerprint, not IP**: client-supplied visitor
  id (frontend-generated UUID in localStorage, sent as a header), hashed
  server-side with a salt; clients that send none fall back to the
  visits-style `ip + user-agent` hash.
- **Authenticated requests bypass the quota** (any valid `AuthBearer` token);
  logged-in users keep the ordinary rate throttles only.
- **Quota observability**: success responses carry `X-Quota-Remaining`; the
  429 body states the reset time.
- **Reset semantics**: calendar day (default) or ISO week, configurable.

## Capabilities

### New Capabilities

- `anonymous-availability-quota`: free-tier request quota with fingerprint
  identity, login-wall on exhaustion, daily/weekly reset, quota headers.

### Modified Capabilities

(none yet — once `api-throttling` is archived, its spec gains a requirement
about composition: quota is evaluated after the rate throttle, with distinct
error codes; that delta lands with this change's implementation.)

## Impact

- **Code**: availability controllers (or a small quota service + decorator),
  visitor-id header handling, day-keyed quota counters (DB table), quota
  settings component; frontend login CTA on `anonymous_quota_exceeded`
  (frontend repo).
- **API**: new 429 error code + `X-Quota-Remaining` header on availability
  endpoints; version-bump decision deferred to implementation (new response
  header is additive, new error code on a documented status may not be).
- **Privacy**: fingerprint material is hashed server-side, never stored raw
  (GDPR); counter retention bounded by the reset window.
- **Dependencies**: reuses `AuthBearer` and the visits hashing pattern; no
  new infrastructure.

## Status

Proposal only — intentionally **not** scheduled. Implement when scraping or
API-cost pressure actually materializes (see `design.md` open questions).
