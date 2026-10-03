# Why

Group icons in the frontend are currently picked from Iconify at runtime
(`fluent-emoji-flat:*` names): search depends on a third-party API, keyword
data is bolted on client-side (emojibase, lazy-loaded), and icon identity
is an external string we do not control. The product decision is Fluent
Emoji only — all three styles (Color / Flat / High Contrast map cleanly to
our visual modes detailed / reduced / mono). Owning the set in the backend
gives stable IDs, localized search in our four UI languages, a browsable
taxonomy, and no third-party dependency in the picker.

## What Changes

- Import **all** icons from `microsoft/fluentui-emoji` (MIT) at a pinned
  ref: metadata + one SVG per style (Color, Flat, High Contrast), stored
  as static assets; slugs equal the upstream names (which mirror Unicode
  CLDR short names).
- Import **localized keywords** per icon (de/en/fr/it) from CLDR-derived
  data (emojibase-data, MIT) so search works in every UI language without
  client-side fetches.
- New capability `emoji-icon-library`: an icon registry model + management
  command + read-only API endpoint with ranked, localized, typo-tolerant
  search and category facets.
- The frontend picker (separate PR) switches from the Iconify runtime to
  this endpoint; stored legacy names keep rendering via Iconify as a
  transitional fallback.

## Capabilities

### New Capabilities

- `emoji-icon-library`: registry + import of the Fluent Emoji set (three
  styles) with localized keywords, categories, and a searchable read API.

### Modified Capabilities

(none — additive; no existing spec covers icons)

## Impact

- **New models**: `EmojiIcon` (slug, unicode hexcode, CLDR group/subgroup,
  curated flag, upstream ref), `EmojiIconKeyword` (icon, locale, keyword),
  per-style asset paths (static files, no media uploads)
- **Import**: management command `import_fluent_emoji --ref <pin>`; pulls
  the upstream repo archive + emojibase keyword JSON; idempotent re-run;
  records upstream version/license for attribution tooling
- **API**: `GET /v1/icons` — `search`, `lang`, `style`, `category`,
  `curated`, `limit/offset`; responses include per-style asset URLs
- **Search design (decision)**: categories alone are too coarse to search
  on — they become *browse facets* (CLDR groups/subgroups: Smileys &
  Emotion, People & Body, Animals & Nature, Food & Drink, Travel & Places,
  Activities, Objects, Symbols, Flags), while matching runs on
  localized keywords + slug with prefix > substring > fuzzy (Levenshtein
  ≤ 2) ranking. A `curated` flag marks the activity shortlist the picker
  shows before any query.
- **Dependencies**: none new at runtime (import-time fetch only);
  assets served from static storage
- **Out of scope**: user-uploaded custom icons; per-user icon favorites
  (both are follow-ups once settings sync exists)
