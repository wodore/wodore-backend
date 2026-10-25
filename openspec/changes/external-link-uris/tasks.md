# Tasks: external-link-uris

## 1. URI-kind vocabulary & icons

- [ ] 1.1 Data migration seeding the `uri` parent category with
      children `uri.phone`, `uri.email`, `uri.website` (active,
      ordered, slug-stable, idempotent rerun), each with its accepted
      schemes and health-check policy in `extra`
      (`uri.phone` → `{"schemes": ["tel"], "health_check": false}`,
      `uri.email` → `{"schemes": ["mailto"], "health_check": false}`,
      `uri.website` → `{"schemes": ["http", "https"], "health_check":
      true}`) — mirroring the `role.*` seed from `geoplace-parties`
- [ ] 1.2 Source phone / mail / link SVGs via the frontend **Iconify
      agent** (Material Symbols / Lucide style: `phone`, `mail`/
      `alternate_email`, `link`) and curate them through the
      `server/apps/symbols` pipeline (color + mono `Symbol` rows,
      content-hashed, licensed); record the pinned upstream refs
- [ ] 1.3 Wire the curated symbols to the URI-kind categories'
      `symbol_color` / `symbol_mono` (data migration or admin step so
      `resolve_symbol_urls` resolves per kind)

## 2. Scheme-aware ExternalLink

- [ ] 2.1 Replace `ExternalLink.url` `URLField` with a scheme-aware
      `CharField(max_length=200)` + scheme-dispatch validators (http(s)
      → `URLValidator`; `tel:` → RFC 3966 format; `mailto:` → address
      check); applied to every i18n URL variant; `AlterField`
      migration (same column type/width — no data rewrite)
- [ ] 2.2 Add `uri_kind` FK → Category (RESTRICT), scoped to
      the `uri` parent in `clean()` and the admin (the `role` scoping
      precedent); migration + index; introduced nullable — the NOT
      NULL `AlterField` follows the 2.6 backfill
- [ ] 2.3 Derive `uri_kind` in the model save path: when a URL value
      is entered or changed, set/update the kind to the vocabulary
      kind whose accepted schemes contain the URL's scheme; unknown
      scheme → validation error; manual override honored only within
      the kind's accepted schemes (covers admin forms, imports and
      schema write paths uniformly — no endpoint or signal)
- [ ] 2.4 `ExternalLink.clean()`: per-language scheme ∈
      `uri_kind.extra["schemes"]` consistency + URI well-formedness
      (a kind whose schemes exclude a populated URL is rejected — no
      null case). Mirror the check in the schema/import write paths
      (the `GeoPlaceParty.clean()` + `_write_party_associations`
      precedent — `save()` skips `clean()`)
- [ ] 2.5 Gate `save()`'s web-only auto-behaviours
      (`_auto_detect_source`, `_auto_extract_title`, `check_health`)
      behind an http(s) check so `tel:`/`mailto:` saves do no network
      I/O; `check_health()` refuses non-web URLs defensively
- [ ] 2.6 Data migration backfilling the existing http(s) links to
      `uri_kind=uri.website` (expected: all ~92k; assert the count),
      then an `AlterField` making `uri_kind` NOT NULL — backfill
      first, constraint second (the place-detail-endpoint
      slug-invariant pattern). Backfill as a single bulk
      `UPDATE … SET uri_kind_id = … WHERE uri_kind_id IS NULL` (one
      statement, sub-second on ~92k rows) — never per-row `save()`;
      the NOT NULL alter's table scan is trivial at this size, and
      the `url` URLField→CharField alter rewrites nothing (same
      column type/width)
- [ ] 2.7 Unit tests: tel/mailto storable; scheme↔kind mismatch
      rejected; unknown scheme rejected; derivation sets the kind on
      enter and re-derives it on URL change; kindless save rejected
      (NOT NULL); non-web save performs no network I/O

## 3. Health-check policy

- [ ] 3.1 Health-check selector (command/task) filters to kinds whose
      `extra["health_check"]` is true (web), skipping `tel:`/`mailto:`;
      per-link `run_health_check` override preserved
- [ ] 3.2 Confirm `response_code_valid` constraint still holds for
      exempt links (`response_code` null); tests: website checked,
      phone/email skipped (no `last_checked`/`response_code`, no false
      review transition)

## 4. Phone normalization & data migration

- [ ] 4.1 Add `phonenumbers` dependency (`pyproject.toml` + lockfile,
      `--extra private` lane sync)
- [ ] 4.2 Normalization helper: parse with `phonenumbers` (region
      default from place `country_code`, then `CH`, else flag) →
      E.164 → `tel:` URL; unit tests incl. national + unparseable
- [ ] 4.3 Data migration: every `AmenityDetail.phones` entry →
      get_or_create `uri.phone` `ExternalLink` (E.164, label preserved,
      `run_health_check=False`, `skip_health_check=True`) +
      `GeoPlaceExternalLink` to the detail's place; idempotent (keyed on
      normalized URL + place); unparseable numbers recorded for review,
      not dropped; normalization + identifier generation reimplemented
      on historical models (the `parties.0002` precedent — no app-code
      imports)

## 5. API: links member & phones retirement

- [ ] 5.1 `prefetch_links` + `build_links_data(place, request)` in
      `presenters.py`: `[{uri, url, label, symbol}]` (uri = kind
      identifier, symbol via `resolve_symbol_urls` over the `uri_kind`
      category); active/public/review-`done` only — mirroring
      `prefetch_parties`/`build_parties_data`
- [ ] 5.2 `LinkSchema` + `links: list[LinkSchema] | None` on the
      merged `GeoPlaceDetailSchema` (PR #418) under `fields[places]`,
      sibling of `categories`/`sources`/`parties`; nested
      `fields[links]` narrowing; `field_selected` gating skips the
      prefetch when unselected — the member joins the schema's
      `fields[places]` allowlist additively
- [ ] 5.3 Remove the amenity `phones` member: drop `phones` from
      `AmenityDetailSchema`, `build_amenity_detail`, the amenity input
      schema, and `AmenityDetail._trackable_fields`; stop writing
      `phones` in `AmenityDetail.update_or_create`; keep the DB column
      one release for rollback (cleanup deferred)
- [ ] 5.4 Schema + response tests: detail carries `links`; narrowed
      selection skips link queries; only public/done links surface;
      amenity block has no `phones`; phones now appear under `links`

## 6. Version registry & snapshot

- [ ] 6.1 Amend the *unreleased* `VersionChange` in
      `server/apps/apiversions/registry.py`: extend the description with
      the amenity `phones` removal (sunset window 0, zero consumers — the
      PR #418 / 2026-10-02 precedent); no downgrade transform needed for
      a zero-consumer removal
- [ ] 6.2 Regenerate and commit the OpenAPI snapshot (`app
      api_snapshot`); `python3 -m server.apps.apiversions.
      registry_check` passes (no stacking)

## 7. Verification

- [ ] 7.1 Lane-DB dry-runs: vocabulary seed (uri.* present with
      metadata); URL backfill count; phone conversion counts
      before/after, idempotent rerun, unparseable tally; website
      health-check still runs, tel/mailto skipped
- [ ] 7.2 Full lane test suite (`scripts/lane-run.sh .venv/bin/pytest`),
      pyrefly + ruff clean, and a work doc under `_work/`
- [ ] 7.3 PR labels `type:feature` + `api:breaking` (both changelogs
      per the `api-changelog` capability — no manual changelog entries)
      — **applies at PR creation time**
- [ ] 7.4 Frontend: regenerate the API client (the `amenity.phones`
      member is gone; the `links` member is new) — **separate repo,
      follow-up**
