# Proposal: party-slug-minting

## Why

Party slugs are machine-normalized names (`name.lower().replace(" ",
"_")[:50]` — e.g. `coop_supermarkt_bahnhofstrasse`) and double as the
import dedup key (`get_or_create(slug=...)`). They surface in public
API responses (`parties[].slug`) and look nothing like the geoplace
slug concept (short, readable `{base}-{random}`, ≤15 chars, minted
once): parties got the leftover underscore style because the write path
needed a deterministic key, not because anyone chose that public
identifier.

## What Changes

- **Generic slug-minting helper** in `server/core/utils.py` —
  `mint_short_slug(name, *, fallback, ignore_words, max_length=15)`:
  deterministic readable base (slugify, configurable ignore words,
  ≤3 words, ~9-char target, configurable fallback for empty names) plus
  a random `[a-z0-9]` suffix sized 5–8 chars from the remaining space;
  no DB access. Extracted verbatim from
  `GeoPlace.generate_unique_slug`, which becomes a thin wrapper (public
  signature and outputs unchanged).
- **Party identity split**: new unique `Party.dedup_key` — the
  normalized name (exactly today's `_normalize_party_slug`, so
  re-imports keep matching migrated rows); `slug` becomes a minted
  short public identifier (geoplace style, hyphen separator), minted
  once at creation.
- **Write paths dedup by key**: the OSM import (precache + write
  path), `_write_party_associations`, `import_parties` /
  `parties.services.merge_owner`, and the provisioning migration
  resolve parties by `dedup_key`; `PartyInput.slug` becomes optional
  (reference an existing party by slug; otherwise the name resolves or
  mints via the key).
- **Data migration** (parties): backfill `dedup_key` from `slug`
  (identity for every existing row), then re-mint all slugs from the
  localized names — chunked and memory-bounded per the geoplace re-mint
  pattern (#422).
- **Admin**: dedup key shown read-only; a blank slug is minted on save.

Not an API contract change: the `parties[].slug` *shape* is unchanged,
only values are re-minted — the same data-only re-mint the geoplace
slugs already went through (no new API version; litmus test: a pinned
client keeps working, it just sees new slug values once).

## Capabilities

### New Capabilities

- `short-slug-minting`: the generic helper and the model contracts
  (GeoPlace behavior-preserved delegation, Party minted-once slugs
  keyed by dedup key).

### Modified Capabilities

- `geoplace-parties`: *Party entity* (slug semantics + dedup key) and
  the slug-derivation wording in *Brand category replacement* /
  *Owner merge* scenarios.

## Impact

- Code: `server/core/utils.py`, `parties` (model, services, command,
  admin), `geometries` (OSM import, `_write_party_associations`,
  `PartyInput`), migrations; tests for all of the above.
- API: `parties[].slug` values change once (re-mint) — do it now while
  no client has cached party slugs (#415 just merged).
- Rollout: schema (add unique nullable key) → backfill → swap import
  dedup → re-mint, in that order, one migration chain.
