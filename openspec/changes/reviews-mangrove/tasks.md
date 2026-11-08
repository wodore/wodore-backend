# Tasks: reviews-mangrove

All backend tasks are implementable as-is; each section lands testable
(`inv tests` / `scripts/lane-run.sh .venv/bin/pytest`). The frontend
section (11) is **informative only — explicitly out of scope for this
change** (separate repo, separate proposal). Phase-2 items (sections 9–10)
are decided but sequenced after the first release cut.

## 1. App scaffold, settings, models

- [ ] 1.1 Create `server/apps/reviews` app (apps.py, `__init__.py`,
      empty admin/models/api split per AGENTS.md structure), add to
      `INSTALLED_APPS`, add the Unfold tab (models: ReviewerKey,
      ReviewerProfile, SubmittedReview, ReviewBlacklist)
- [ ] 1.2 Settings component `server/settings/components/reviews.py`:
      `MANGROVE_API_BASE_URL` (default `https://api.mangrove.reviews`),
      `MANGROVE_ENABLED` kill-switch, timeout/retry constants,
      `MANGROVE_U_RADIUS` (default 30, per design O1),
      `MANGROVE_CACHE_TTL_LIST/SUMMARY`, `MANGROVE_QUOTA_SUBMIT/EDIT`,
      `MANGROVE_CLIENT_ID`, `MANGROVE_KEY_ENCRYPTION_KEY` (Infisical-backed;
      dev default)
- [ ] 1.3 Models + migration: `ReviewerKey` (1:1 User, `kid` PEM
      whitespace-normalized + unique index, private JWK encrypted via
      Fernet/MultiFernet under the dedicated key, minted_at),
      `ReviewerProfile` (1:1 User, nickname default minted non-identifying,
      language), `SubmittedReview` (append-only: user FK, hut slug,
      subject URI, action, iat, signature + unique index, JWT verbatim,
      attempt state), `ReviewBlacklist` (signature + reason + created_by +
      unique index) — `TimeStampedModel`/`BaseManager` conventions, Unfold
      admin for all four
- [ ] 1.4 Tests: model constraints (one key per user, unique signatures,
      blacklist dedup), encryption round-trip (value at rest ≠ plaintext,
      decrypts correctly), nickname minting never derives from account
      fields

## 2. MangroveClient: subject recipe + read calls

- [ ] 2.1 `client.py`: `subject_for_hut(hut) -> str` pure function
      (`geo:{lat:.6f},{lon:.6f}?q={urlencode(slug)}&u={settings…}`,
      PostGIS WGS84 → 6-decimal formatting, tests pin byte-stability,
      rename/translation invariance, distinct huts never matching under
      the q-equal + u-sum rule)
- [ ] 2.2 `MangroveClient` (httpx): base URL/timeout from settings;
      methods `list_reviews(sub, limit)`, `subject_aggregate(sub)`,
      `batch_aggregates(subs)`, `review(signature)`, `issuer(pem)`,
      `submit(jwt)`; connect/read timeouts; GET-only bounded retries with
      backoff; writes fail fast (never retried); one structlog event per
      call (endpoint, subject, status, duration — never opinion/nickname),
      Sentry span `mangrove.request`
- [ ] 2.3 Typed response models (pydantic) for the 0.2.0 endpoints:
      review item, subject aggregate, issuer stats, batch response —
      defensive parsing (unknown fields ignored; missing essential fields
      → `UpstreamUnavailable`)
- [ ] 2.4 Contract fixtures: record live 0.2.0 responses under
      `server/apps/reviews/fixtures/mangrove/` + contract tests replaying
      them through the client; error translation test (timeout/5xx/garbage
      body → `UpstreamUnavailable`, raw body only in logs); document the
      recapture helper (dev-only, not CI)
- [ ] 2.5 Tests: `respx`-mocked behaviors (retry budget, no-retry-on-
      submit, timeout mapping), logging assertions (no review PII in
      events)

## 3. Identity: signing service + key custody

- [ ] 3.1 `signing.py`: ES256 JWT construction per MaReSt v0.7.0 —
      header `{alg, typ, kid: <pem>, jwk: <JSON string, key_ops
      ["verify"]>}`; builders: review claims (`iat`, `sub`, `rating`
      and/or `opinion`, `images`, `metadata`), `edit`/`delete`/
      `report_abuse` actions (`sub: urn:maresi:{sig}`), generic
      `equivalence` builder (reserved for later, not exposed via API);
      tests verify signatures against the embedded kid/jwk and MaReSt
      field limits (rating 0–100 int, opinion ≤1000, images ≤5 ×
      `{src, label ≤50}`, metadata allowlist)
- [ ] 3.2 Key service: lazy mint on first write (ES256 P-256), encrypted
      persistence, `kid` normalization (insignificant whitespace), lookup
      by kid (which user wrote this); ownership check helper (target
      review kid == caller kid) used by edit/delete
- [ ] 3.3 Tests: lazy mint idempotency, ownership check unit tests,
      MaReSt compliance suite over generated JWTs (decode + verify +
      field-limit rejects)

## 4. Read endpoints

- [ ] 4.1 `api.py` read controllers: `GET /v1/huts/{slug}/reviews`
      (anonymous, envelope `data`/`count`, newest-first with latest-edit
      collapse, `lang` query, pagination; 404 for non-public/inactive
      huts; empty collection for unknown subjects; blacklist filter;
      envelope `license: CC-BY-4.0` + attribution), name= == operation_id
      per E003/E004
- [ ] 4.2 `GET /v1/huts/{slug}/reviews/summary` + batch summary endpoint
      (bounded slug list, upstream `POST /batch` chunking, zeroed
      aggregates for zero-review huts, oversized-list 400)
- [ ] 4.3 Caching: Django-cache keyed subject (+lang/pagination);
      `cache_headers` + CDN-Tag `api:reviews` on reads; `no-store` on
      writes; write-through invalidation helper (list + summary + batch
      keys) — tests for key coverage and TTL config
- [ ] 4.4 Contract tests per endpoint: envelope shape, error bodies
      (RFC 9457 members), upstream-failure → 503 `upstream_unavailable`
      (mocked client), blacklist exclusion from list/count/aggregates,
      hut ETag regression (hut detail endpoints unchanged)

## 5. Write endpoints: submit, edit, delete, report, my-reviews

- [ ] 5.1 `POST /v1/huts/{slug}/reviews` (`AuthBearer`): DTO validation
      (rating and/or opinion; images; metadata subset — unknown keys →
      `review_invalid_*` 400), server-side enrichment (`client_id`,
      `license: CC-BY-4.0`, `osm_id` from the hut's existing OSM
      `HutSource` linkage when present, language default from request),
      sign + relay, 201 with created review incl. signature,
      `SubmittedReview` log write, write-through invalidation; OpenAPI
      description states Mangrove ToS/CC-BY-4.0 publication
- [ ] 5.2 `PATCH …/{signature}` (edit) and `DELETE …/{signature}`
      (delete): local ownership check before signing, relay
      `action:edit/delete` JWTs, 200/204 responses, cache invalidation,
      log updates; 403 path signs nothing
- [ ] 5.3 `POST …/{signature}/report` (report_abuse, no ownership,
      reason as opinion, no rating)
- [ ] 5.4 `osm_id` stamping: submit path resolves the hut's current OSM
      link from the existing `HutSource` (org `osm`, import-pipeline-fed)
      → `metadata.osm_id` (`node/ID[/VERSION]` form, ≤50); absent link
      submits without the field; tests for both paths
- [ ] 5.5 Quota service: per-user rolling window (submit vs edit/delete
      classes, defaults from settings), 429 `review_quota_exceeded` with
      reset time; tests for window rollover and class separation
- [ ] 5.6 `GET /v1/me/reviews` (`AuthBearer`): upstream kid-listing,
      subject→hut slug resolution (huts annotation absent for
      non-Wodore subjects), latest-edit collapse, deleted excluded
- [ ] 5.7 Contract tests per write endpoint (auth 401s, validation 400s,
      quota 429s, ownership 403s, upstream rejection sanitized, relay
      payload assertions against mocked client)

## 6. Moderation + admin

- [ ] 6.1 `ReviewBlacklist` admin: list/filter/actions (bulk blacklist by
      pasted signature), reason audit; read-path filter tests (list,
      count, summary, batch) already covered by 4.4 — add admin action
      tests
- [ ] 6.2 `SubmittedReview` admin (read-only, filter by user/hut/action,
      export selected rows as JSONL — the archival/export path from the
      mangrove-client spec)

## 7. Docs, snapshots, release plumbing

- [ ] 7.1 Verify no `Api-Version` bump: endpoints additive; run
      `app api_snapshot` and confirm the diff is purely additive (no
      transforms registered); CI labels for the eventual PR: `type:*` +
      `api:added`
- [ ] 7.2 AGENTS.md: reviews section (app layout, subject recipe, key
      custody + rotation runbook, quota/blacklist pointers); `docs/` note
      referencing the openspec change
- [ ] 7.3 Infisical: register the new env vars (staging + prod), document
      `MANGROVE_KEY_ENCRYPTION_KEY` rotation (MultiFernet add-new-keep-old)
      in the runbook
- [ ] 7.4 Full suite green: `inv tests`, `inv check.types` (pyrefly
      strict — full annotations, no baseline), `inv lint`

## 8. Pre-release verification (spikes, informative)

- [ ] 8.1 Equivalence spike (design O2): on a staging/dev keypair, file
      an equivalence claim between two reserved test subjects
      (`geo:0,0?q=Test&u=100` family), observe whether
      api.mangrove.reviews resolves it in aggregation; document findings
      in `_work/` + design.md addendum — outcome gates future
      slug↔OSM-name bridging, not v1 behavior
- [ ] 8.2 Contact ORA (hello@open-reviews.net / links on
      open-reviews.net) about: equivalence-resolution status, partner
      onboarding (Swiss tourism portals), upstream contract changelog
      practice; record answers in the same note
- [ ] 8.3 Live smoke (staging, manual): submit→list→edit→delete round
      trip on a reserved test subject via the staging API; confirm CDN
      purge behavior on the `api:reviews` tag

## 9. Phase 2 — identity import/export (decided, later release)

- [ ] 9.1 `GET /v1/me/reviews/identity` (export private JWK string,
      re-authentication required) and `PUT /v1/me/reviews/identity`
      (import JWK: re-derive kid, verify ES256 shape, rebind account —
      one active key per account; old key dropped after confirmation of
      the first successful action under the new key)
- [ ] 9.2 Tests: export/import round-trip, imported-key ownership
      checks, re-auth enforcement, erasure command coverage of imported
      reviews (kid-listing sweep)

## 10. Phase 2 — erasure automation

- [ ] 10.1 `reviews_erase_user` management command: sign+relay `delete`
      for every authorable review (submission log + upstream kid
      listing), destroy key/profile/log rows; wire as account-deletion
      hook; export mode dumps the log first
- [ ] 10.2 Tests: full erasure, other users untouched, upstream-failure
      retry semantics (command is resumable)

## 11. Frontend (wodore-frontend-quasar) — INFORMATIVE, NOT THIS CHANGE

Not part of `reviews-mangrove`; tracked here so the intent is not lost.
Any of these belongs to a frontend proposal of its own.

- [ ] 11.1 Hut page (`/hut/:slug`): review list section (rating stars,
  opinion, nickname, date, images) + submit/edit/delete/report UI bound
  to the new endpoints; CC-BY-4.0 attribution + Mangrove ToS notice in
  the submit flow
- [ ] 11.2 Star ↔ rating mapping UX: 5 stars ↔ 0/25/50/75/100
  (likelihood-to-recommend semantics in the tooltip copy); API stays
  integer 0–100
- [ ] 11.3 Map badges: batch summary endpoint feeding count/mean chips on
  clustered and raw POI markers (zoom-aware batching)
- [ ] 11.4 Profile "my reviews" section (`GET /v1/me/reviews`),
  including imported-identity reviews without hut annotation
- [ ] 11.5 Later: JWK import/export UI (bring your MapComplete identity),
  OSM-preference sync, `did:web` display once upstream is live
