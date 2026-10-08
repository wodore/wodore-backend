## Context

The frontend group-icon picker currently:

1. Searches Iconify's public API (`prefixes=fluent-emoji-flat`),
2. Lazy-loads emojibase-data (MIT, CLDR-derived) client-side for
   de/fr/it keyword search, mapping hits to `fluent-emoji` slugs,
3. Falls back to a small in-app fuzzy matcher,
4. Renders picks at runtime via `@iconify/vue`.

This works but: search quality depends on two CDNs, keyword data ships to
every client (~95 KB/locale), and icon identity is an external namespace.

Requirements have evolved beyond the first draft of this change:
icons are **uploaded at runtime** (media storage, not static files), the
registry must serve **any icon set** (emoji today, map overlays next), and
packs must stay **open-ended** (no fluent/noto enum anywhere in the
schema or code).

## Goals / Non-Goals

- Goals: pack-organized searchable icon registry; maximal reuse of
  existing models (`Symbol`, `Category`, `License`, `Organization`);
  runtime-replaceable assets; localized server-side search; stable clean
  slugs; three visual-mode variants per icon.
- Non-goals: uploads by end users; per-user favorites; consolidating
  meteo's `WeatherCodeSymbolCollection` onto the new `SymbolCollection`
  (follow-up change); re-implementing Unicode CLDR tooling (we consume
  emojibase-data JSON).

## Decisions

### D1: Assets are `Symbol` rows (media, runtime) — not static files

Every SVG becomes a `Symbol`: media `svg_file` storage, review workflow,
admin, imagor pipeline, and the existing `/v1/symbols` endpoints come for
free, and curators can replace an SVG at runtime. `Symbol` uniqueness is
`(slug, style)`, and packs share slug spaces (fluent `tent`, noto `tent`)
— so asset slugs carry a pack prefix (`fluent-emoji-tent`), exactly the
meteo pattern (`weather-icons-*`, `meteoswiss-*`). The clean upstream
slug lives on `Icon`. Slot name equals `Symbol` style: the import maps
Fluent Color → style `detailed`, Flat → `simple`, High Contrast → `mono`.

### D2: Packs = `SymbolCollection`, open-ended (no family enum)

A pack is a row in a new `SymbolCollection` model in the symbols app —
same shape as meteo's `WeatherCodeSymbolCollection` (unique slug,
`source_org` FK). `fluent-emoji` and `noto-emoji` are just the first two
rows; overlays would be another. Creating a pack is a data operation, not
a code change. Migrating meteo onto this model is an explicit follow-up,
not part of this change.

### D3: `Icon` is Category-shaped, with `(pack, slug)` uniqueness

One row per icon per pack. Fields deliberately follow `Category`'s
conventions: `slug`, i18n `name` (modeltrans), `order`, `is_active`, and
the symbol trio FKs named `symbol_detailed` / `symbol_simple` /
`symbol_mono` — the exact field names `resolve_symbol_urls()` already
expects, so URL serialization works unchanged. Uniqueness is
`UniqueConstraint(pack, slug)` — the same composite-scoping pattern as
Category's `unique_slug_per_parent` — with a NOT NULL `pack` (avoids the
Postgres NULLs-distinct hole that nullable scopers have). `Icon` adds
what `Category` cannot carry: nullable indexed `unicode` hexcode (join
key for keyword data; optional — identity is the slug) and the keyword
index. A dedicated
model is required: `Category`'s identity is position in the place taxonomy
(`(slug, parent)`), an icon's identity is membership in a pack — shared-
tree icons would collide across packs, per-pack trees would duplicate the
taxonomy × N.

### D4: CLDR taxonomy = real `Category` tree, FK to the subgroup only

Groups/subgroups are `Category` rows: root `emoji` → 9 CLDR groups →
subgroups, names localized from emojibase-data `messages.json` into
`Category.i18n` — mirroring how the meteo importers build the `meteo`
tree. `Icon.category` is a nullable FK pointing only at the **subgroup**
(lookup constrained to non-root parents); the group resolves one join up
(`select_related("category__parent")`) — the same shape as
`WeatherCode.category`. The tree is shared across packs: cross-pack slug
collisions are impossible because uniqueness lives on `(pack, slug)`, not
in the tree. Verified safe for existing consumers: the overlays endpoint
and the admin tile map filter root categories through the explicit
`CATEGORY_REGISTRY` whitelist, and the roots-loading `Category.values`
classproperty has no callers.

### D5: Keywords from emojibase-data (CLDR), folded for matching

`emojibase-data/<locale>/data.json` (MIT) provides labels + tags in our
four UI languages. Import maps hexcode → keywords (`Icon.unicode`, FE0F
stripped). English slugs come from the same data (parity with upstream
names), validated during import: upstream slugs without a keyword match
(a handful of brand/flag cases) are recorded as unmatched, not imported
keywords. Keywords are stored accent- and case-folded for matching, with
the original retained for display.

### D6: Search runs on keywords; taxonomy is for browsing

Categories are browse facets, not the search index (a search for "zelt"
must not require knowing the Travel & Places group). Matching runs on
`IconKeyword` + slug with prefix > substring scoring and Levenshtein ≤ 2
typo tolerance for terms ≥ 4 chars, capped by `limit/offset`. Curated
shortlists are `IconCuratedList` rows (unique slug, admin-managed
membership via a timestamped through model — the ETag keys on it):
`activities` is seeded with the basic activity icons; overlays, basemap
markers etc. are just more lists. The import never touches them, so
re-imports cannot clobber manual curation.

## Risks / Trade-offs

- Volume: ~6k `Icon` rows + ~10k `Symbol` rows — unremarkable for
  Postgres; the Symbol admin gains pack/style filters if noise becomes
  an issue. Icons are managed through the pack-scoped Icon admin.
- Asset churn: replacing/deleting `Symbol` rows is guarded by the review
  workflow; Icon slots are `SET_NULL` like Category's symbol FKs.
- Upstream emoji additions require re-running the import (quarterly
  releases; the command is idempotent and records the pinned ref).
- Fuzzy matching CPU is bounded by term length ≥ 4 and a cap on
  candidates scanned per request; measured in tests.

## Migration Plan

1. Models + migrations + import command + tests (no API change).
2. `GET /v1/icons` + OpenAPI docs; frontend picker PR switches to it,
   keeping the Iconify runtime only for legacy stored names.
3. Legacy name mapping command (`tabler:*`, `wd-*`, layer-icon slugs →
   nearest imported slug) ships with the settings-sync change.
4. Follow-up change: consolidate meteo's `WeatherCodeSymbolCollection`
   onto `SymbolCollection`.
