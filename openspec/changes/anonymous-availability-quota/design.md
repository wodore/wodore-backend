## Context

Deliberately unscheduled follow-up to `api-throttling`: that change caps
request *rate* per client IP (120/min, 2000/day); this one caps free
*volume* per identified visitor and asks heavy users to log in. The user
intent captured 2026-10: "20 requests free, then login required
(fingerprinted), resets daily or weekly".

Existing building blocks:

- `AuthBearer` (`server/apps/api/auth.py`) — complete bearer auth with
  scopes/roles/groups, wired to no endpoint yet.
- Visits fingerprint pattern (`server/apps/visits/models.py::_visitor_key`)
  — first-XFF + user-agent, sha256, cache-only, no PII.
- Rate throttling + shared `throttling` cache alias from `api-throttling`.

## Goals / Non-Goals

**Goals**

- Anonymous visitors get N free availability requests per window
  (default 20/day), counted per **visitor fingerprint**, not IP.
- Exhaustion → machine-readable `anonymous_quota_exceeded` the frontend
  turns into a login prompt; logging in lifts the quota.
- Reset semantics configurable: calendar day (default) or ISO week.
- Privacy-preserving identity: hashes only, bounded retention.

**Non-Goals**

- Device attestation / Play Integrity / browser challenges — stronger
  identity can slot in later behind the same quota interface.
- Billing or tiered quotas beyond free vs logged-in.
- Applying the quota beyond the availability endpoints.

## Decisions (draft — to finalize at implementation)

### D1 — Visitor identity: client-supplied id, hashed server-side

Frontend generates a UUID v4 once, stores it in localStorage, sends it as
`X-Visitor-Id`. Server hashes it with a per-deployment salt (settings) →
quota key. Fallback for clients that send nothing: visits-style
`ip + user-agent` hash. Rationale: honest visitors are stable across IP
changes (mobile!); the fallback keeps the no-JS/headless case bounded.
Rotation (clear localStorage) resets the free tier — accepted abuse floor,
raisable later with attestation.

### D2 — Counters: day-keyed rows, cache-first

`AnonymousQuotaUse(fingerprint_hash, window_start, count)` upserted via the
shared `throttling`/DB cache with write-behind (visits-buffer pattern) so
the request path stays cache-only; flushed by the existing q2 machinery or
a trivial threshold task. Calendar-day reset falls out of the key; ISO week
uses `date.isocalendar()`.

### D3 — Response contract

- Success: `X-Quota-Remaining: <n>` (and `X-Quota-Limit`).
- Exhaustion: 429, body `{"code": "anonymous_quota_exceeded", "detail": …}`
  including reset timestamp; distinct from rate-throttle 429
  (`{"code": "throttled", …}` — name pinned at implementation) so the
  frontend can react differently (login CTA vs back-off).
- `AuthBearer`-authenticated requests: quota skipped entirely.

### D4 — Order of evaluation

Rate throttle first (cheap, protects the origin), then quota (identity
semantic). A request rejected by rate throttling does not consume quota.

## Open Questions

- O1: Fingerprint hardening — is UUID+fallback enough, or add UA/Accept
  entropy to the fallback; do we cap per-IP *distinct* visitor-ids (sybil
  brake: e.g. 50 ids/day/IP)?
- O2: Quota bucket scope — shared across all three availability endpoints
  (assumed in D2) or per endpoint?
- O3: Login requirements — any registered account vs verified email; is
  account creation self-service at that point?
- O4: Default window — daily (assumed) or weekly? Reset at UTC midnight vs
  Europe/Zurich?
- O5: Versioning — new error code on a documented 429 + new headers:
  bump an API version or treat as additive (lean additive; decide with
  the registry litmus test at implementation).
- O6: GDPR/DSG — salted-hash storage + retention window sign-off
  (counters expire with the window; document in privacy policy).

## Migration / Rollout

1. Ship quota counting as observability-only (headers, no enforcement) —
   measure real visitor distributions.
2. Pick defaults from data (is 20/day the right cliff?).
3. Enable enforcement behind an env flag; frontend ships the login CTA.
