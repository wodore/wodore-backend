## Status: proposal only — not scheduled

This change is intentionally left unimplemented (see proposal
"Status"). Tasks below are the implementation sketch for whenever it is
picked up; nothing here is done.

## 1. Identity & counters

- [ ] 1.1 Visitor-id handling: accept `X-Visitor-Id`, salted-hash server-side (salt via settings/infisical); fallback hash from IP + user-agent (visits pattern)
- [ ] 1.2 Quota counter storage: window-keyed counts in the shared cache with write-behind flush (visits-buffer pattern) or a small `AnonymousQuotaUse` table — decide per measured volume
- [ ] 1.3 Window math: calendar day / ISO week switch (`ANONYMOUS_QUOTA_WINDOW`), reset timestamps in Europe/Zurich vs UTC (resolve O4)

## 2. Enforcement & contract

- [ ] 2.1 Quota check composed after rate throttling on the three availability controllers (distinct code path, no quota consumption on rate-rejected requests)
- [ ] 2.2 429 body `anonymous_quota_exceeded` with reset time; `X-Quota-Remaining`/`X-Quota-Limit` on successes
- [ ] 2.3 AuthBearer bypass: authenticated requests skip quota entirely
- [ ] 2.4 Env knobs: quota size (default 20), window mode, enforcement flag (observability-only first — see design "Migration / Rollout")

## 3. Hardening & open questions (resolve first)

- [ ] 3.1 Decide O1–O6 from design.md (sybil cap per IP, bucket scope, login requirements, versioning, privacy sign-off)
- [ ] 3.2 Observability phase: deploy counting without enforcement; measure visitor distributions to sanity-check the 20/day cliff

## 4. Client & docs

- [ ] 4.1 Frontend: visitor id generation/storage, login CTA on `anonymous_quota_exceeded` (frontend repo)
- [ ] 4.2 API docs: quota semantics, headers, error code; snapshot + versioning decision per O5
- [ ] 4.3 Privacy note: hashed-only storage and retention window into the privacy policy
