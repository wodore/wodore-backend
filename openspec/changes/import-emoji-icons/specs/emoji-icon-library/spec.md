## ADDED Requirements

### Requirement: Fluent Emoji import at a pinned ref
The system SHALL provide a management command that imports the complete
`microsoft/fluentui-emoji` set from a pinned upstream ref, storing for
every icon its slug (upstream name), unicode hexcode (variation selectors
stripped), CLDR group and subgroup, and one SVG asset per style (Color,
Flat, High Contrast). Re-running the command at the same or a newer ref
SHALL be idempotent and SHALL record the imported upstream ref.

#### Scenario: Full import

- WHEN an operator runs `import_fluent_emoji --ref <pin>`
- THEN every upstream icon exists exactly once with slug, hexcode, group,
  subgroup, and three style asset paths
- AND the upstream ref and license (MIT) are recorded

#### Scenario: Idempotent re-run

- WHEN the command runs again at the same ref
- THEN no duplicate icons, keywords, or assets are created

### Requirement: Localized keywords (de/en/fr/it)
The import SHALL attach localized labels and keywords per icon for the
UI languages German, English, French, and Italian, sourced from
CLDR-derived data (emojibase-data) joined on the unicode hexcode. Keywords
SHALL be stored accent- and case-folded for matching, with the original
form retained for display.

#### Scenario: German keyword search

- WHEN a client searches `zelt` with `lang=de`
- THEN icons whose German keywords include `zelt` (e.g. tent) are returned

#### Scenario: Unmatchable upstream icons

- WHEN an upstream slug has no keyword-data match (e.g. certain flags)
- THEN the icon imports without keywords and remains findable by slug

### Requirement: Searchable icons endpoint
The system SHALL expose `GET /v1/icons` with `search`, `lang`, `style`,
`category`, `curated`, `limit`, and `offset` parameters. Search SHALL
match localized keywords and slug with prefix ranking above substring
ranking, SHALL apply typo tolerance (edit distance ≤ 2) for terms of at
least 4 characters when no exact matches exist, and SHALL return each
icon's slug, unicode, category, subcategory, curated flag, and per-style
asset URLs. Empty search with `curated=true` SHALL return the curated
shortlist ordered by a stable sort key.

#### Scenario: Ranked localized search

- WHEN `search=zelt&lang=de`
- THEN results are ordered with prefix keyword matches first, then
  substring matches, and include tent/camping icons

#### Scenario: Typo tolerance

- WHEN `search=montain&lang=en` (typo)
- AND no exact keyword match exists
- THEN fuzzy matching returns mountain-family icons

#### Scenario: Category facet

- WHEN `category=Travel & Places` with no search term
- THEN all icons in that CLDR group are returned, paginated

#### Scenario: Curated shortlist

- WHEN `curated=true` with no search term
- THEN the curated activity shortlist is returned

### Requirement: Read-only, cacheable serving
The icons endpoint SHALL be public, read-only, and cacheable (ETag or
equivalent); icon assets SHALL be served from static storage with long
cache lifetimes. Import runs SHALL NOT affect serving availability.

#### Scenario: Caching

- WHEN the same icons request is repeated within the cache window
- THEN the response is served from cache without recomputation
