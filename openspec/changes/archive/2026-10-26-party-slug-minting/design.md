# Design: party-slug-minting

## Context

`Party.slug` today is the deterministic `name.lower().replace(" ",
"_")[:50]` (`_normalize_party_slug` in the OSM import) — chosen so
`get_or_create(slug=…)` dedups re-imports. Consequence: the public
identifier is a long machine string in underscore style, exposed via
`parties[].slug`. GeoPlace solved the same tension years ago:
`GeoPlace.generate_unique_slug` builds `{base}-{random}` (≤15 chars,
suffix 5–8 `[a-z0-9]`, base ~9 chars from up to 3 filtered words) and
dedups through a separate identity. Migration 0054 re-minted ~187k
geoplace slugs chunked under a 512 Mi migrate budget — the pattern to
copy.

Second thread: manual association edits. Only the party inline wired
protection (`save_formset` marks `is_modified` + flat `"parties"` in
`protected_fields`), and that flat entry blocks *all* party writes for
the place. Links and categories inlines marked nothing, and the OSM
import wrote links unconditionally.

Stakeholders: OSM import (idempotence), wodore hut import (owner
merge), admin (creation/protection UX), public API (`parties[].slug`).

## Goals / Non-Goals

- Goals: one generic mint helper shared by both models; short readable
  party slugs; import idempotence preserved without a dedicated
  identity column; role-scoped party protection; links/categories
  shielded on manual edits; single re-mint migration, before clients
  cache party slugs.
- Non-Goals: changing geoplace slugs (behavior-preserving refactor
  only); a source/identity association table for parties; renaming
  anything in the public API contract.

## Decisions

1. **Helper in `server/core/utils.py`, name-derived base + sized
   random suffix, no DB access.** `mint_short_slug(name, *,
   fallback, ignore_words=(), max_length=15)`; extraction verbatim
   from `GeoPlace.generate_unique_slug`, which stays as a wrapper
   passing the geoplace specifics (`SLUG_IGNORE_WORDS` amenity words,
   category fallback, `"place"`). Alternatives: keep two
   implementations (the duplication this removes); `shortuuid` (new
   dependency, lookalikes, whole-id random).

2. **Identity in `Party.extra` JSONB (`osm_name`), not a column.**
   `extra` follows the `GeoPlace.extra` / `GeoPlaceSource.extra`
   pattern (default dict + GIN index). `osm_name` = the normalized
   name (verbatim the OSM import's former `_normalize_party_slug`) —
   owner slugs ride the same key (already normalized). No unique
   constraint on the JSONB path: imports are single-process, and the
   resolver (decision 3) makes cross-writes converge. Alternatives: a
   unique `dedup_key` column (worked, but the explicit ask was slug +
   extras only); name lookup without an identity (racy, i18n-messy).

3. **Shared resolver with name adoption** —
   `parties.services.resolve_party_by_name(name, *, review_status)`:
   resolve by `extra.osm_name`; on miss, adopt an exactly-matching
   base-`name` row by stamping the identity onto it; else create with
   minted slug. Manual parties therefore dedupe with imports on first
   touch (the semantics the auto-derived `dedup_key` had). The OSM
   import (both precache paths), `_write_party_associations`
   (name-only `PartyInput`), and the owner merge (keyed by
   `normalize_key(owner.slug)`) all resolve through it/keys.

4. **Slug minted once, at creation, never re-derived.** `Party.save()`
   mints when blank (base: name → `extra.osm_name` fallback →
   `"party"`); collisions are probabilistic (≥36⁵ suffix space) — same
   posture as geoplace runtime minting.

5. **Role-scoped party protection in `protected_fields`.** Entries may
   be structured: `{"parties": ["role.brand"]}` shields exactly those
   roles; the legacy flat `"parties"` string still shields all (never
   narrowed silently — kept when present). `GeoPlace.
   protected_party_roles()` resolves the scoped entries;
   `_write_party_associations(..., respect_protection=True)` filters
   per role (and honors a flat entry directly). The admin party inline
   records the union of roles touched (changed + new + deleted rows).

6. **Links/categories: flat marking + an import gate.** The
   `save_formset` wiring extends to the external-link and category
   inlines (flat `"links"` / `"categories"` — no scoping axis yet);
   the OSM import's `_add_external_link` returns early for
   `"links"`-protected places. The bulk link-reconciliation DELETE is
   *not* gated (pre-existing behavior, separate follow-up if wanted).

7. **One migration chain: add `extra` → backfill identity → re-mint →
   shrink.** `parties.0003`: backfill `extra.osm_name = slug` (the
   slug *was* the identity), re-mint via the helper (chunked 2 000,
   collision-domain set, re-runnable exclude of already-minted
   `^[a-z0-9]{1,9}-[a-z0-9]{5,8}$`), then `ALTER` slug to varchar(15)
   — order matters, legacy slugs are up to 50 chars. Reverse: noop
   (re-minted slugs not recoverable; same call as the geoplace
   re-mint).

## Risks / Trade-offs

- [Public `parties[].slug` values change once] → Mitigation: #415 is
  days old, no released client caches party slugs; minted-once rule
  means never again.
- [No DB-enforced uniqueness on `extra.osm_name`] → Mitigation:
  single-process imports + the adoption resolver; a duplicate would
  need two concurrent writers. A unique expression index can be added
  later without schema churn if this ever bites.
- [Name adoption merges two genuinely distinct same-named parties] →
  accepted: adoption is intentionally lossy — the normalized-name
  identity has always collapsed same names (pre-parties slug identity
  did the same); editors split genuinely distinct parties in the
  admin. Identity uniqueness on ``extra.osm_name`` is enforced by
  convention (single-process imports + the resolver), not by the
  database — a unique expression index can be added without schema
  churn if concurrent writers ever appear (advisor review finding 4).
- [Wodore hut import still bails on coarse `is_modified`] → known
  inconsistency, pre-existing source policy, out of scope here.

## Migration Plan

1. `parties.0003` runs on deploy (add → backfill → re-mint → shrink).
2. New code resolves parties by identity; admin marks scoped
   protection on manual edits.
3. Tests: full suite green (984 passed), pyrefly strict 0 errors.
