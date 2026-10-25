# Design: party-slug-minting

## Context

`Party.slug` today is the deterministic `name.lower().replace(" ",
"_")[:50]` (`_normalize_party_slug` in the OSM import) — chosen so
`get_or_create(slug=…)` dedups re-imports. Consequence: the public
identifier is a long machine string in underscore style, exposed via
`parties[].slug`. GeoPlace solved the same tension years ago:
`GeoPlace.generate_unique_slug` builds `{base}-{random}` (≤15 chars,
suffix 5–8 `[a-z0-9]`, base ~9 chars from up to 3 filtered words) and
dedups through a *separate* identity (source organization + source_id).
Migration 0054 (place-detail-endpoint) just re-minted ~187k geoplace
slugs chunked under a 512 Mi migrate budget — the pattern to copy.

Stakeholders: OSM import (idempotence), wodore hut import (owner
merge), admin (creation UX), public API (`parties[].slug` consumers).

## Goals / Non-Goals

- Goals: one generic mint helper shared by both models; short readable
  party slugs; import idempotence preserved bit-for-bit; single re-mint
  migration, done before clients cache party slugs.
- Non-Goals: changing geoplace slugs (behavior-preserving refactor
  only); a source/identity association table for parties; renaming
  anything in the public API contract.

## Decisions

1. **Helper in `server/core/utils.py`, name-derived base + sized
   random suffix, no DB access.**

   `mint_short_slug(name, *, fallback, ignore_words=(), max_length=15)`
   → `{base}-{suffix}`; base via slugify + ignore-word filter + ≤3-word
   smart split (~9-char target) or `fallback` when the name is empty;
   suffix length `max(5, min(8, max_length - len(base) - 1))` from
   `secrets.choice` over `[a-z0-9]`; result clamped to `max_length`.
   Extraction is verbatim from `GeoPlace.generate_unique_slug`; the
   classmethod stays as a wrapper passing the geoplace specifics
   (`SLUG_IGNORE` amenity words, category fallback, `"place"`) so every
   existing call site and output distribution is unchanged.

   Alternatives: keep two implementations (the duplication this change
   removes); `shortuuid` (new dependency, base57 includes lookalikes,
   and we want the base readable, not the whole id random).

2. **Identity: unique `Party.dedup_key`, normalization unchanged.**

   `dedup_key = _normalize_party_slug(name)` (lower, spaces→`_`,
   `[:50]`) — exactly the slug derivation today, so 0053-migrated,
   owner-merged, and OSM-minted rows keep matching on re-import. Owner
   merge keys by `owner.slug` as today (already normalized) so the
   provisioning migration's earlier runs stay idempotent. Uniqueness:
   same-entity collision is the status quo (normalized name *was* the
   unique slug); distinct parties sharing a name were already merged
   before this change.

   Alternatives: lookup by `name` without a key (racy `get_or_create`,
   i18n fields, no index); a `GeoPlaceSource`-style association table
   (parties are source-agnostic — one brand row is written by OSM and
   referenced by huts alike; a per-source key table would fragment
   dedup instead of centralizing it).

3. **Slug minted once, at creation, never re-derived.**

   `Party.save()` mints when `slug` is blank (covers admin creation and
   any forgotten path); write sites `get_or_create(dedup_key=…,
   defaults={"slug": mint_short_slug(name)})`. Re-imports hit the key
   and leave the slug alone. Minted slugs use hyphens (base and
   separator), matching the geoplace public style.

   Collisions: no DB check in the helper (same as geoplace); 36⁵ ≈ 60M
   suffix space against ~10³ parties ≈ 10⁻⁵ — and creation sites can
   simply retry on `IntegrityError`. Not worth a probe query in the hot
   path.

4. **`PartyInput.slug` optional; resolution order slug → key → mint.**

   Callers that know a party pass its slug (stable reference); OSM just
   passes `name` (+ role). `_write_party_associations` resolves:
   existing slug match → existing `dedup_key(normalize(name))` → create
   with minted slug. `import_parties` and the provisioning migration
   get the same key-based get_or_create via `parties.services`.

5. **One migration chain: add column → backfill → re-mint.**

   `dedup_key` nullable-unique-added, backfilled `dedup_key = slug`
   (identity for all existing rows — today slug *is* the key), then
   enforced unique; slugs re-minted from the best available name
   (`name` or key title-cased as 0053 did), chunked at 2 000 rows
   (parties are ~10²–10³, but the shape matches 0054 and costs
   nothing). Reverse: restore `dedup_key = slug` … slugs are not
   recoverable → reverse is a no-op with the mapping retained in git
   history (same call as the geoplace re-mint).

## Risks / Trade-offs

- [Public `parties[].slug` values change once] → Mitigation: #415 is
  days old, no released client caches party slugs; re-mint now and
  never again (minted-once rule).
- [Two parties legitimately share a name (two local clubs)] →
  Mitigation: pre-existing condition (they shared a slug before);
  editors split them in the admin — `dedup_key` edit is admin-only,
  `slug` stays free.
- [Admin saves a party with a hand-typed slug that collides] →
  Mitigation: unique constraint surfaces as a validation error, same as
  today.
- [Helper extraction subtly changes geoplace slugs] → Mitigation:
  wrapper is verbatim-pass-through; existing `generate_unique_slug`
  tests must stay green untouched, plus property-style checks that
  outputs match the documented examples.

## Migration Plan

1. `parties.0003`: add nullable `dedup_key` (+ backfill + unique
   enforcement) and re-mint slugs — one migration, ordered operations.
2. Deploy: migration runs before the new code serves traffic (standard
   migrate-then-release), so key-based lookups find backfilled rows.
3. Follow-ups in the same release: OSM import / write path / admin
   switch to key-based dedup.
