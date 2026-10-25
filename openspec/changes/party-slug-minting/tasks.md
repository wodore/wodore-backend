# Tasks: party-slug-minting

## 1. Generic helper

- [x] 1.1 Extract `mint_short_slug` (base derivation + sized random
      suffix, no DB access) into `server/core/utils.py`; move the
      geoplace `SLUG_IGNORE` amenity words and the `"place"` /
      category fallbacks into call-site arguments; unit tests for
      truncation, fallback, ignore words, suffix bounds
- [x] 1.2 Make `GeoPlace.generate_unique_slug` a thin wrapper over the
      helper (signature and outputs unchanged); existing slug tests
      green untouched

## 2. Party model & migration

- [x] 2.1 Add unique `Party.dedup_key` (+ index); `save()` mints a
      short slug via the helper when blank; model tests (mint-once,
      uniqueness errors, key normalization matches
      `_normalize_party_slug`)
- [x] 2.2 `parties.0003`: add nullable column → backfill
      `dedup_key = slug` → enforce unique → re-mint all slugs from
      names (chunked, 0054 pattern); no-op reverse; migration test
      (backfill identity, re-mint shape, idempotent re-run)

## 3. Write paths

- [x] 3.1 `_write_party_associations`: `PartyInput.slug` optional;
      resolve slug → dedup key → create with minted slug; schema tests
      (existing-by-slug, existing-by-name, new-mint, role validation
      unchanged)
- [x] 3.2 OSM import: drop slug computation from the two precache
      `get_or_create` sites and the `PartyInput` construction — dedup
      by key, name drives minting; import tests updated
- [x] 3.3 `import_parties` + `parties.services.merge_owner` (+ note
      the provisioning migration already ran — command remains the
      re-sync): key-based get_or_create; command tests updated
- [x] 3.4 API response tests: `parties[].slug` values are minted-style
      after the migration; shape and field selection unchanged

## 4. Admin & verification

- [x] 4.1 Party admin: dedup key read-only display; blank-slug save
      mints (admin test)
- [x] 4.2 Full suite on the lane runner, pyrefly strict, ruff; lane
      dry-runs of the migration against lane data; work doc under
      `_work/`
