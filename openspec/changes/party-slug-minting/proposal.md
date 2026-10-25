# Proposal: party-slug-minting

## Why

Party slugs are machine-normalized names (`name.lower().replace(" ",
"_")[:50]` — e.g. `coop_supermarkt_bahnhofstrasse`) and double as the
import dedup key (`get_or_create(slug=...)`). They surface in public
API responses (`parties[].slug`) and look nothing like the geoplace
slug concept (short, readable `{base}-{random}`, ≤15 chars, minted
once). Separately, manual party edits in the admin protect party
writes wholesale — a hand-edited brand also blocks operator updates.

## What Changes

- **Generic slug-minting helper** in `server/core/utils.py` —
  `mint_short_slug(name, *, fallback, ignore_words, max_length=15)`:
  deterministic readable base (slugify, configurable ignore words,
  ≤3 words, ~9-char target, configurable fallback) plus a random
  `[a-z0-9]` suffix sized 5–8 from the remaining space; no DB access.
  Extracted from `GeoPlace.generate_unique_slug`, which becomes a thin
  wrapper (public signature and outputs unchanged).
- **Party identity without a dedicated column**: `Party.extra` JSONB
  (GIN-indexed, same pattern as `GeoPlace.extra`) carries
  `osm_name` — the normalized name (exactly the former
  `_normalize_party_slug`, so re-imports keep matching migrated rows;
  owner slugs ride the same key). `slug` becomes a minted short public
  identifier, minted once at creation (`save()` when blank).
- **Shared resolver with name adoption**: `parties.services.
  resolve_party_by_name` resolves by `extra.osm_name`; when no row
  carries the identity yet, a party whose base `name` matches exactly
  is adopted (the identity is stamped onto it) — manually created
  parties dedupe with imports instead of duplicating. Used by the OSM
  import (both precache paths), the schema write path, and (keyed by
  owner slug) the owner merge.
- **Data migration** (parties.0003): backfill `extra.osm_name` from
  `slug` (identity for every existing row), then re-mint all slugs via
  the helper (chunked, memory-bounded, re-runnable per the #422/0054
  pattern), then shrink the slug column to 15.
- **Role-scoped party protection**: `protected_fields` entries may be
  structured — `{"parties": ["role.brand"]}` shields only the listed
  roles; the legacy flat `"parties"` string still shields all roles.
  The admin party inline records the roles an edit touched
  (`GeoPlace.protected_party_roles()` resolves); the schema update
  paths filter entries per role (`_write_party_associations`,
  `respect_protection=True`).
- **Links and categories protection**: manual external-link and
  category inline edits now mark the place (`"links"` /
  `"categories"` flat entries — previously they marked nothing), and
  the OSM import's `_add_external_link` skips protected places.
- **`PartyInput.slug` optional**: reference an existing party by slug;
  otherwise the name resolves (identity/adoption) or mints.

Not an API contract change: the `parties[].slug` *shape* is unchanged,
only values are re-minted — data-only, like the geoplace re-mint (no
new API version; litmus test: a pinned client keeps working).

## Capabilities

### New Capabilities

- `short-slug-minting`: the generic helper and the model contracts
  (GeoPlace behavior-preserved delegation; Party minted-once slugs,
  identity in `extra.osm_name` with name adoption; role-scoped party
  protection).

### Modified Capabilities

- `geoplace-parties`: *Party entity* (extra identity, minted slug),
  the slug-derivation wording in *Brand category replacement* /
  *Owner merge*, and *Admin management* (role-scoped protection;
  links/categories marking).

## Impact

- Code: `server/core/utils.py`, `parties` (model, services, command,
  admin), `geometries` (OSM import, `_write_party_associations`,
  `PartyInput`, GeoPlace resolver, place admin), migrations; tests.
- API: `parties[].slug` values change once — now, before clients cache
  them. `protected_fields` gains a structured entry shape (admin +
  imports only, not public).
- Rollout: add `extra` → backfill identity → re-mint → shrink column,
  one migration chain, ordered operations.
