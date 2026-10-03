## Context

The frontend group-icon picker currently:

1. Searches Iconify's public API (`prefixes=fluent-emoji-flat`),
2. Lazy-loads emojibase-data (MIT, CLDR-derived) client-side for
   de/fr/it keyword search, mapping hits to `fluent-emoji` slugs,
3. Falls back to a small in-app fuzzy matcher,
4. Renders picks at runtime via `@iconify/vue`.

This works but: search quality depends on two CDNs, keyword data ships to
every client (~95 KB/locale), icon identity is an external namespace, and
the app's other three Fluent styles (Color, High Contrast) are unused even
though they map to the planned detailed/reduced/mono visual modes.

## Goals / Non-Goals

- Goals: own the icon set + searchable metadata; one endpoint the picker
  queries; localized search server-side; stable slugs; style variants.
- Non-goals: uploads, favorites, sync with user settings (follow-ups),
  re-implementing Unicode CLDR tooling (we consume emojibase-data JSON).

## Decisions

### D1: Source of truth = upstream repo at a pinned ref

`microsoft/fluentui-emoji` release archive (MIT). Slug = folder name
(equals CLDR English short name, e.g. `snow-capped-mountain`). Import
keeps `unicode` (hexcode, without FE0F variation selectors) as the join
key for keyword data. Re-imports are idempotent; upstream ref recorded.

### D2: Keywords from emojibase-data (CLDR), not hand-written

`emojibase-data/<locale>/data.json` (MIT) provides labels + tags in our
four UI languages. Import maps hexcode → keywords. English slugs come
from the same data (parity with upstream names), validated during import:
every upstream slug must resolve (a handful of brand/flag exceptions are
recorded as unmatched, not imported keywords).

### D3: Categories = CLDR groups/subgroups as FACETS, search on keywords

Answering "categories or something new": **both, with distinct roles**.
CLDR groups/subgroups become stable `category`/`subcategory` fields for
browsing; they are deliberately NOT the primary search index (a search
for "zelt" must not require knowing the Travel & Places category).
Matching: normalized (accent-folded, case-folded) keyword/slug index with
prefix > substring scoring, plus Levenshtein ≤ 2 typo tolerance on terms
≥ 4 chars, capped result set with `limit/offset`.

### D4: One model, three style asset paths

`EmojiIcon` stores `svg_color` / `svg_flat` / `svg_high_contrast` paths
into static storage (files are immutable per upstream ref; serving via
static avoids media-storage churn). The API returns all three URLs; the
frontend picks by visual mode.

### D5: `curated` flag for the shortlist

The picker's pre-query grid is a product-curated activity list (~18
icons). A boolean `curated` flag on `EmojiIcon` keeps that list in the
backend (single source, updateable without frontend releases) instead of
hardcoding slugs.

## Risks / Trade-offs

- Upstream icon additions require re-running the import (fine: quarterly
  emoji releases; command is idempotent and versioned).
- Fuzzy matching server-side adds CPU; bounded by term length ≥ 4 and a
  cap on candidates scanned per request; measured in tests.
- Static-asset storage grows ~10 MB per style set (≈30 MB total) —
  acceptable for static hosting/CDN.

## Migration Plan

1. Import command + models + tests (no API change).
2. API endpoint + docs; frontend picker PR switches to it, keeping the
   Iconify runtime ONLY for legacy stored names.
3. Legacy name migration command (`tabler:*`, `wd-*`, layer-icon slugs →
   nearest Fluent slug) ships with the settings-sync change.
