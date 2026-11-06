# Tasks: party-slug-minting

## 1. Generic helper

- [x] 1.1 Extract `mint_short_slug` (base derivation + sized random
      suffix, no DB access) into `server/core/utils.py`; geoplace
      `SLUG_IGNORE_WORDS`/category fallback become call-site
      arguments; unit tests for truncation, fallback, ignore words,
      suffix bounds
- [x] 1.2 Make `GeoPlace.generate_unique_slug` a thin wrapper over the
      helper (signature and outputs unchanged); existing slug tests
      green untouched

## 2. Party model & migration

- [x] 2.1 Add `Party.extra` JSONB (+ GinIndex); `save()` mints a short
      slug when blank (base: name → `extra.osm_name` → "party"); model
      tests (mint-once, explicit slug kept, extra never invented,
      uniqueness errors)
- [x] 2.2 `parties.0003`: add `extra` → backfill `osm_name = slug` →
      re-mint all slugs via the helper (chunked, collision-domain set,
      re-runnable minted-shape exclude) → shrink the column to 15;
      no-op reverse; migration tests (backfill identity + noop,
      re-mint shape/uniqueness/key stability, idempotent re-run)

## 3. Write paths

- [x] 3.1 `resolve_party_by_name` in `parties.services` (identity
      lookup → same-name adoption → create with minted slug) shared by
      the OSM import (both precache paths) and the name-only
      `PartyInput` branch of `_write_party_associations`; `PartyInput.
      slug` optional (slug reference → name resolve/mint; both missing
      rejected); tests including manual-party adoption
- [x] 3.2 `import_parties` + `merge_owner`: identity-keyed lookups
      (`extra.osm_name`, owner slug); command tests updated
      (idempotent re-run keeps the minted slug)
- [x] 3.3 API response tests: `parties[].slug` values are minted-style
      after the migration; shape and field selection unchanged

## 4. Role-scoped protection & siblings

- [x] 4.1 `GeoPlace.protected_party_roles()` resolver; `_write_party_
      associations(respect_protection=True)` filters per role and
      honors the legacy flat entry; both schema update gates pass it;
      tests (scoped skip, union block, flat blocks all, unprotected
      writes all, resolver shape)
- [x] 4.2 Admin `save_formset`: party inline records the touched roles
      (changed + new + deleted; legacy flat kept), links/categories
      inlines mark flat `"links"` / `"categories"`; OSM import
      `_add_external_link` skips `"links"`-protected places; admin
      tests (role recording, merge, flat kept, link/category marking,
      unchanged formset no-op)

## 5. Verification

- [x] 5.1 Full suite on the lane runner with `--create-db` (rewritten
      migration), pyrefly strict 0 errors, ruff check + format clean;
      work doc under `_work/`
