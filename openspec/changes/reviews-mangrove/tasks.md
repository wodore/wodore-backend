# Tasks: reviews-mangrove

Backend tasks are implementable as-is; each section lands testable
(`inv tests` / `scripts/lane-run.sh .venv/bin/pytest`). The frontend
section (11) is **informative only — explicitly out of scope for this
change** (separate repo, separate proposal). Phase-2 items (section 10)
are decided but sequenced after the first release cut.

## 0. Upstream verification (spike) — DONE 2026-11-08

- [x] 0.1 Live probes against reserved test subjects only
      (`geo:0,0?q=Test&u=100` family; findings logged in
      `_work/261108_mangrove_spike.md`): live API is **0.4.1** (docs state
      + `POST /submit`, `/dump`, `/stats/clients`, `/identity/{id}`
      present); `POST /submit` takes the JWT as `text/plain` and returns
      the literal `true` (no signature — derive locally); opinion-only and
      rating-only submissions both accepted; `q` matching is
      case/punctuation-normalized (accent `É` did NOT fold); a
      zero-credibility key's equivalence claim does not surface foreign
      reviews in `GET /reviews?sub=`; `latest_edits_only` default true;
      full dataset available via `GET /dump` (14 504 reviews; images
      persist to `files.mangrove.reviews`)
- [x] 0.2 Derived decisions folded into design.md: local aggregates (D6),
      anti-injection geo filter (D6), image-host allowlist default (D9),
      erasure idempotency (D4), equivalence campaign deferred (D7/O2)

## 1. App scaffold, settings, models

- [x] 1.1 Create `server/apps/reviews` app (apps.py, `__init__.py`), add to
      `INSTALLED_APPS`, add the Unfold tab (models: ReviewerKey,
      ReviewerProfile, SubmittedReview, ReviewBlacklist)
- [x] 1.2 Settings component `server/settings/components/reviews.py` +
      include in the split-settings list: `ORA_API_BASE_URL`,
      `ORA_ENABLED` kill-switch (false → writes 503
      `service_unavailable`, reads serve empty collections),
      `ORA_TIMEOUT_CONNECT/READ`, `ORA_U_RADIUS` (30),
      `ORA_CACHE_TTL_LIST/SUMMARY`, `ORA_QUOTA_SUBMIT/EDIT`,
      `ORA_CLIENT_ID`, `ORA_IMAGE_HOST_ALLOWLIST`
      (default `["files.mangrove.reviews"]`), `ORA_THROTTLE_*`
      (read/batch burst+daily), `ORA_KEY_ENCRYPTION_KEY` (dev default
      **hard-refused outside `DJANGO_ENV=development|test`**, mirroring
      `LOCAL_AUTH_ENABLED`)
- [x] 1.3 Models + migration: `ReviewerKey` (1:1 User `on_delete=PROTECT`,
      `kid` single-line PEM whitespace-normalized + unique index, private
      JWK encrypted via Fernet/MultiFernet under the dedicated key,
      minted_at), `ReviewerProfile` (1:1 User PROTECT, minted
      non-identifying nickname default, language), `SubmittedReview`
      (append-only: user FK PROTECT, hut slug, subject URI, action,
      iat, derived signature + unique index, JWT verbatim, state
      pending/accepted/failed), `ReviewBlacklist` (signature + reason +
      created_by + unique index) — `TimeStampedModel`/`BaseManager`
      conventions, Unfold admin for all four
- [x] 1.4 Tests: model constraints (one key per user, unique signatures,
      blacklist dedup, PROTECT refuses user deletion while reviews exist),
      encryption round-trip (value at rest ≠ plaintext), nickname minting
      never derives from account fields
- [x] 1.5 Register `review_quota_exceeded` in
      `server/apps/api/error_codes.py` (`ErrorCode` + `PROBLEM_TITLES`);
      update the codes-completeness test

## 2. Open ReviewsClient: subject recipe + read calls

- [x] 2.1 `client.py`: `subject_for_hut(hut) -> str` pure function
      (`geo:{lat:.6f},{lon:.6f}?q={urlencode(slug)}&u={settings…}`,
      WGS84 → 6-decimal formatting) + `subject_geo_matches(subject,
      hut_subject)` normalized-q + radius-sum predicate (the D6 filter);
      tests pin byte-stability, rename/translation invariance, and the
      normalized-uniqueness invariant (two huts within 2u whose slugs
      normalize equal → reported)
- [x] 2.2 `Open ReviewsClient` (httpx): base URL/timeout from settings;
      methods `list_reviews(sub)`, `review(signature)`,
      `issuer(pem)`, `submit(jwt)` (`POST /submit`, text/plain body);
      connect/read timeouts; GET-only bounded retries with backoff;
      writes fail fast (never retried); one structlog event per call
      (endpoint, subject, status, duration — never opinion/nickname),
      Sentry span `mangrove.request`
- [x] 2.3 Typed response models (pydantic) for the 0.4.1 endpoints:
      review list item (`did?`, `geo?`, `jwt`, `kid`, `original_sub?`,
      `payload`, `scheme?`, `signature`), issuer stats, batch/subject
      aggregates — defensive parsing (unknown fields ignored; missing
      essential fields → `UpstreamUnavailable`)
- [x] 2.4 Contract fixtures recorded under
      `server/apps/reviews/fixtures/mangrove/` (reserved test subjects
      ONLY — never real subjects; requires §3 signing for the submit
      fixture) + contract tests replaying them through the client; error
      translation test (timeout/5xx/garbage body → `UpstreamUnavailable`,
      raw body only in logs); dev-only recapture helper documented (not
      CI)
- [x] 2.5 Tests with `respx` (add as dev dependency): retry budget,
      no-retry-on-submit, timeout mapping, logging assertions (no review
      PII in events)

## 3. Identity: signing service + key custody

- [x] 3.1 `signing.py` on `cryptography` (P-256 ECDSA/SHA-256, DER→raw
      r‖s conversion — no JOSE dependency): header `{alg, typ, kid:
      <single-line pem>, jwk: <JSON string, key_ops ["verify"]>}`;
      builders: review claims, `edit`/`delete`/`report_abuse` actions
      (`sub: urn:maresi:{sig}`), generic `equivalence` builder (not
      exposed via API); derived signature = JWT third segment
- [x] 3.2 Key service: lazy mint on first write, encrypted persistence,
      `kid` normalization, lookup by kid; caller resolution helper
      (session user or `request.auth["sub"]` → User)
- [x] 3.3 Tests: MaReSt compliance over generated JWTs (decode + verify
      against embedded kid/jwk; rating 0–100, opinion ≤1000 code points,
      images ≤5 × `{src https, label ≤50}`, metadata allowlist, flags
      only-when-true), lazy-mint idempotency, ownership checks

## 4. Read endpoints

- [x] 4.1 `api.py` read controllers: `GET /v1/huts/{slug}/reviews`
      (anonymous, envelope `data`/`count`, newest-first, local pagination
      `limit`≤100/`offset`; 404 for non-public/inactive huts; empty
      collection for unknown subjects; blacklist + geo-match filter;
      envelope `license: CC-BY-4.0` + attribution; image allowlist at
      serving) — one operation per path, name= == operation_id per
      E003/E004
- [x] 4.2 `GET /v1/huts/{slug}/reviews/summary` + batch
      `GET /v1/reviews/summary?slugs=…` (≤50, sorted/dedup,
      canonicalized cache key; aggregates computed locally from the
      cached filtered list: count, rating_count, rating_mean,
      positive_count, opinion_count; oversized → 400)
- [x] 4.3 Caching: Django-cache list keyed by subject, summary keyed by
      subject; short public `Cache-Control` on reads (120 s) via
      `cache_headers`; dmr rate throttles on reads + batch; write-through
      invalidation helper (list + summary keys)
- [x] 4.4 Wire the routers in `server/apps/api/api_v1.py`
      (`Router("huts/", reviews_api.hut_paths)`,
      `Router("reviews/", reviews_api.paths)`, `my/` include for
      my-reviews)
- [x] 4.5 Contract tests per endpoint: envelope shape, RFC 9457 error
      bodies, upstream-failure → 503 `service_unavailable` (mocked
      client), blacklist exclusion from list/count/aggregates, geo-match
      filter, hut ETag regression (hut detail endpoints unchanged),
      throttle wiring

## 5. Write endpoints: submit, edit, delete, report

- [x] 5.1 `POST /v1/huts/{slug}/reviews/submit` (`AuthBearer`): pydantic
      DTO `extra="forbid"` (validation → standard `validation_error`),
      enrichment (`client_id`, `license: CC-BY-4.0`, `osm_id` from
      existing HutSource linkage when present, nickname/language
      defaults), sign + relay, log row pending→accepted/failed, 201 with
      created review incl. derived signature, write-through
      invalidation; OpenAPI description states Open Reviews ToS/CC-BY-4.0
      publication
- [x] 5.2 `POST …/{signature}/edit` and `POST …/{signature}/delete`:
      target-belongs-to-hut check (sub/original_sub vs subject → 404),
      ownership check (log first, upstream `GET /review` kid fallback)
      before signing, relay, cache invalidation; delete idempotent
      (upstream refusal for already-deleted = success); 403 path signs
      nothing
- [x] 5.3 `POST …/{signature}/report` (report_abuse, no ownership,
      required reason ≤1000 as opinion, no rating, rate-throttled)
- [x] 5.4 `osm_id` resolution: `HutSource.objects.filter(hut=hut,
      organization__slug="osm", is_current=True)` most recent →
      `metadata.osm_id = "{osm_type}/{source_id}"`; validate `osm_type`
      ∈ {node, way, relation} and length ≤50; NEVER append
      `HutSource.version` (internal revision counter, not an OSM
      version); tests for linked/unlinked paths
- [x] 5.5 Quota service: rolling 24 h from `SubmittedReview` rows
      (submit class; edit+delete combined class), 429
      `review_quota_exceeded` + `Retry-After` + reset in body; tests for
      window rollover and class separation
- [x] 5.6 `GET /v1/my/reviews` on `MyApiController`: upstream kid-listing,
      subject→hut slug resolution (annotation absent for non-Wodore
      subjects), latest-edit collapse, deleted excluded
- [x] 5.7 Contract tests per write endpoint (auth 401s, validation 400s,
      quota 429s, ownership 403s, wrong-hut 404s, upstream rejection
      sanitized, relay payload assertions against mocked client)

## 6. Moderation + admin

- [x] 6.1 `ReviewBlacklist` admin: list/filter/actions (bulk blacklist by
      pasted signature), reason audit; admin action tests
- [x] 6.2 `SubmittedReview` admin (read-only, filter by user/hut/action/
      state, export selected rows as JSONL — the archival/export path)

## 7. Erasure (v1)

- [x] 7.1 `reviews_erase_user` management command: sign+relay `delete`
      for every authorable review from the log (idempotent — refusals for
      already-deleted = success), then destroy key/profile/log rows;
      `--export` mode dumps the log first
- [x] 7.2 Tests: full erasure, other users untouched, idempotency,
      PROTECT guard (user deletion without erasure fails)

## 8. Docs, release plumbing

- [x] 8.1 Verify no `Api-Version` bump: endpoints additive — do NOT
      commit an `api_snapshot` (additive changes need none); verify via
      the OpenAPI diff (`dmr_export_schema`) that only new operations
      appear; eventual PR labels: `type:*` + `api:added`
- [x] 8.2 AGENTS.md: reviews section (app layout, subject recipe, key
      custody + rotation runbook, quota/blacklist pointers, kill-switch
      behavior); `docs/` note referencing the openspec change
- [ ] 8.3 Infisical: register the new env vars (staging + prod), document
      `ORA_KEY_ENCRYPTION_KEY` rotation (MultiFernet
      add-new-keep-old) in the runbook
- [x] 8.4 Full suite green: `inv tests`, `inv check.types` (pyrefly
      strict — full annotations, no baseline), `inv lint`

## 8b. Round 2 — review names, provider merge, replies, merge requests (2026-11-08)

- [x] 8b.1 Subject `q` = review name (OSM name → hut name fallback),
      **pinned on the first review write** (`HutReviewSubject` model;
      `resolve_review_name` / `pin_review_name`); slug recipe
      superseded; collision check downgraded to operator warning
- [x] 8b.2 15-minute list TTL + **write-through cache merge**: submit
      prepends, edit updates, delete removes — the author's own write is
      visible on the next read regardless of TTL or upstream indexing
      lag (plain invalidation is not enough — verified in the §0 spike)
- [x] 8b.3 refuges.info read-only provider (`refuges_info.py`):
      comments API client (dict-by-index/list, HTML-cleaned, UTC
      normalized), HutSource org `refuges` point-id linkage, per-review
      `source`/`license`/`link` fields on the merged listing, provider
      failures degrade to Open Reviews-only, blacklist covers provider ids,
      `ORA_REFUGES_INFO_ENABLED` kill-switch
- [x] 8b.4 Replies: `POST …/{signature}/reply` (signed `urn:maresi`
      review, submit quota) + public `GET …/{signature}/replies`
      (per-signature cache, blacklist-filtered)
- [x] 8b.5 Merge requests: `ReviewMergeRequest` model + staff queue in
      Unfold (new/done/rejected) + `POST …/reviews/merge-request`
      (auth; target+note+link); no automatic equivalence filing
- [x] 8b.6 Edit-history answer recorded (design D12): upstream keeps
      original+edits (`latest_edits_only=false` exposes the chain) and
      the local append-only log records every Wodore-signed JWT;
      exposing an endpoint is a documented follow-up, not this round
- [x] 8b.7 Tests: name resolution/pinning, cache merge, provider merge
      + attribution + kill-switch + parsing units, replies, merge
      requests (97 reviews tests green)

## 8c. Round 3 — image gallery provider + reply images (2026-11-08)

- [x] 8c.1 `Open ReviewsProvider` (`server/apps/reviews/images.py`): review
      photos into the standard image pipeline (imagor variants, CC-BY-4.0
      license rows, reviewer attribution, provider fallback entry,
      24 h cache, geo-match + blacklist filters, kill-switched,
      never-raises) — registered in `api_images.py`
- [x] 8c.2 Reply images: `ReviewReplyIn.images` (≤5, https, same
      validation) wired through signing + response DTO
- [x] 8c.3 Spec + design updated (hut-reviews: reply images scenario,
      gallery-provider requirement; design D9)
- [x] 8c.4 Tests: provider unit tests + reply-images test

## 8d. Round 4 — Opus review fixes (2026-11-08)

- [x] 8d.1 Own-write overlay on every list build (log-based, worker- and
      cache-state-independent) + shared DB cache alias — the round-2
      write-through merge was LocMem/per-process and skipped on cold
      cache (Opus B1)
- [x] 8d.2 Upstream-failure guards everywhere (edit/delete/report/reply/
      replies/my-reviews never 500 while upstream is down — 503 instead;
      Opus B2)
- [x] 8d.3 Edit-row handling per live probe: default listings serve the
      EDIT row (action=edit, own signature, original_sub=geo) — kept
      with stable original-signature identity, both-signature
      blacklist, geo-match on original_sub; fixture recorded
      (`reviews_list_edited.json`); edited reviews no longer vanish and
      blacklist escapes via edits are closed (Opus B3)
- [x] 8d.4 `q` encoding verified live: plus-spaces required at submit,
      %20 refused, matching normalizes both, accents percent-encoded
      and not folded — byte-level tests pin the encoder (Opus B4)
- [x] 8d.5 Tests isolated from the live upstream (autouse Open Reviews
      stub; Opus B5)
- [x] 8d.6 refuges.info back-pressure: 2.5 s provider timeout,
      60 s negative cache, shared alias, batch = cached-only provider
      data (Opus B6)
- [x] 8d.7 Image-src strictness: backslash/`@`/whitespace/control/port
      rejected before parsing (parser-confusion bypass closed; Opus B7)
- [x] 8d.8 Gate via the hut's visible list (no upstream call; blacklist
      + provider ids 404), keys minted only on actual writes, pin
      returns the stored name, replies overlay (Opus N1/N3a/N3c/N4/N6)
- [x] 8d.9 `SubmittedReview.subject` widened to 1024 (percent-encoded
      names; Opus N11), specs/design/AGENTS wording aligned (Opus B8),
      116 reviews tests green

## 8e. Round 5 — photo upload relay + provider cache invalidation (2026-11-08)

- [x] 8e.1 `Open ReviewsClient.upload_photos()`: PUT multipart to
      `upload.mangrove.reviews` (verified live 200), returns
      base64url SHA-256 hashes; `photo_url(hash)` builds the public
      `files.mangrove.reviews/<hash>` URL
- [x] 8e.2 `POST /v1/reviews/images` endpoint (authenticated,
      throttled): relays multipart files, validates count (≤5), total
      size (≤4.5 MB), types (JPEG/PNG/GIF/WebP); Wodore stores
      NOTHING — pure relay to the Open Reviews file server
- [x] 8e.3 Provider cache invalidation after submit with images:
      `invalidate_image_provider_cache(hut)` clears the
      Open ReviewsProvider's `(lat, lon, radius)` entries (24 h TTL
      otherwise delays new photos in the gallery)
- [x] 8e.4 FakeClient gains `upload_photos()` for testing; 4 new
      tests (relay, auth gate, validation service, cache
      invalidation); 120 reviews tests green

## 9. Pre-release verification (manual, staging)

- [ ] 9.1 Re-verify upstream contract against live 0.4.x at release time
      (the API is not frozen; re-run the fixture recapture helper on
      reserved test subjects)
- [ ] 9.2 Contact ORA (hello@open-reviews.net / links on
      open-reviews.net): equivalence-resolution status for credible keys,
      partner onboarding (Swiss tourism portals), upstream contract
      changelog practice; record answers in `_work/`
- [ ] 9.3 Live smoke on staging: submit→list→edit→delete round trip on a
      reserved test subject via the staging API

## 10. Phase 2 — identity import/export (decided, later release)

- [ ] 10.1 `GET /v1/my/reviews/identity` (export private JWK string;
      concrete re-authentication defined when built — e.g. OIDC
      `auth_time` within N minutes) and `PUT /v1/my/reviews/identity`
      (import JWK: re-derive kid, verify ES256 shape, rebind account —
      one active key per account)
- [ ] 10.2 Tests: export/import round-trip, imported-key ownership
      checks, erasure coverage of imported reviews (kid-listing sweep)

## 11. Frontend (wodore-frontend-quasar) — INFORMATIVE, NOT THIS CHANGE

Not part of `reviews-mangrove`; tracked here so the intent is not lost.
Any of these belongs to a frontend proposal of its own.

- [ ] 11.1 Hut page (`/hut/:slug`): review list section (rating stars,
  opinion, nickname, date, images) + submit/edit/delete/report UI bound
  to the new endpoints; CC-BY-4.0 attribution + Open Reviews ToS notice in
  the submit flow
- [ ] 11.2 Star ↔ rating mapping UX: 5 stars ↔ 0/25/50/75/100
  (likelihood-to-recommend semantics in the tooltip copy); API stays
  integer 0–100
- [ ] 11.3 Map badges: batch summary endpoint feeding count/mean chips on
  clustered and raw POI markers (zoom-aware batching, ≤50 slugs per call)
- [ ] 11.4 Profile "my reviews" section (`GET /v1/my/reviews`),
  including foreign-subject reviews without hut annotation
- [ ] 11.5 Render review images via imagor (never load third-party hosts
  directly — the API already restricts src to the allowlist)
- [ ] 11.6 Later: JWK import/export UI (bring your MapComplete identity),
  OSM-preference sync, `did:web` display
