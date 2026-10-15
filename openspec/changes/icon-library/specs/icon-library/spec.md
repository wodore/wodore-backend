## ADDED Requirements

### Requirement: Pack-based icon registry
The system SHALL maintain an icon registry organized in packs
(`SymbolCollection`: unique slug, source organization). Every icon
(`Icon`) SHALL belong to exactly one pack, SHALL have a slug unique
within its pack, a localized name, a display order, and up to three
symbol slots (detailed, simple, mono) referencing `Symbol` rows stored in
media storage. An icon MAY reference a subgroup `Category` for taxonomy.
Packs SHALL be open-ended: creating a pack requires no schema or code
change.

#### Scenario: Same slug in two packs

- WHEN packs `fluent-emoji` and `noto-emoji` both contain an icon with
  slug `tent`
- THEN both icons exist independently, each with its own symbol assets
  and keywords, addressable as `(pack, slug)`

#### Scenario: Runtime asset replacement

- WHEN a curator replaces the SVG of a symbol referenced by an icon slot
- THEN subsequent API responses serve the new asset, without re-import

### Requirement: Emoji import at pinned refs
The system SHALL provide a management command that imports the complete
`microsoft/fluentui-emoji` set (primary, MIT) and the Noto Emoji color
set (secondary, Apache-2.0) from pinned upstream refs into the
`fluent-emoji` / `noto-emoji` packs: SVGs stored as `Symbol` rows with
pack-prefixed slugs (upstream styles mapped Color→detailed, Flat→simple,
High Contrast→mono; noto color→detailed only), and icons stored with
their upstream slug, unicode hexcode (variation selectors stripped), and
CLDR group/subgroup as localized `Category` rows under an `emoji` root
(referencing the subgroup only). Re-running the command at the same or a
newer ref SHALL be idempotent and SHALL record the imported refs and
licenses.

#### Scenario: Full import

- WHEN an operator runs `icon_import --source fluent --ref <pin>` (and
  `icon_import --source noto --ref <pin>` for the secondary pack)
- THEN every upstream icon exists exactly once per pack with slug,
  hexcode, taxonomy reference, and its symbol slots populated
- AND the upstream refs and licenses are recorded

#### Scenario: Idempotent re-run

- WHEN the command runs again at the same ref
- THEN no duplicate icons, keywords, symbols, or taxonomy rows are
  created

### Requirement: Localized keywords (de/en/fr/it)
The import SHALL attach localized labels and keywords per icon for the
UI languages German, English, French, and Italian, sourced from
CLDR-derived data (emojibase-data) joined on the unicode hexcode.
Keywords SHALL be stored accent- and case-folded for matching, with the
original form retained for display.

#### Scenario: German keyword search

- WHEN a client searches `zelt` with `lang=de`
- THEN icons whose German keywords include `zelt` (e.g. tent) are
  returned

#### Scenario: Unmatchable upstream icons

- WHEN an upstream slug has no keyword-data match (e.g. certain flags)
- THEN the icon imports without keywords and remains findable by slug

### Requirement: Searchable icons endpoint
The system SHALL expose `GET /v1/icons` with `search`, `lang`, `pack`,
`category`, `list`, `limit`, and `offset` parameters. Search SHALL
match localized keywords and slug with prefix ranking above substring
ranking, SHALL apply typo tolerance (edit distance ≤ 2) for terms of at
least 4 characters when no exact matches exist, and SHALL return each
icon's slug, pack, unicode, category, subcategory, the slugs of curated
lists containing it, and per-slot asset URLs (detailed, simple, mono).
Empty search with `list=<slug>` SHALL return that curated list ordered
by a stable sort key. The endpoint SHALL be additive (no API contract
version bump).

#### Scenario: Ranked localized search

- WHEN `search=zelt&lang=de`
- THEN results are ordered with prefix keyword matches first, then
  substring matches, and include tent/camping icons

#### Scenario: Typo tolerance

- WHEN `search=montain&lang=en` (typo)
- AND no exact keyword match exists
- THEN fuzzy matching returns mountain-family icons

#### Scenario: Category facet

- WHEN `category=<subgroup slug>` with no search term
- THEN all icons in that CLDR subgroup are returned, paginated

#### Scenario: Pack filter

- WHEN `pack=noto-emoji`
- THEN only icons of that pack are returned

#### Scenario: Curated list

- WHEN `list=activities` with no search term
- THEN that curated list is returned (the seeded basic activity
  shortlist by default; further lists are managed in the admin)

### Requirement: Admin-curated lists
The system SHALL maintain named curated icon lists (unique slug,
display name, admin-managed icon membership via a timestamped through
model). Lists SHALL be contextual (e.g. `activities`, `overlays`,
`basemap` markers); creating one SHALL be a data operation. Imports
SHALL NOT create, modify, or delete curated lists or memberships. A
default `activities` list SHALL be seeded with the basic activity
icons, and list membership changes SHALL invalidate the icons-endpoint
cache.

#### Scenario: Manual curation in the admin

- WHEN a curator adds or removes an icon from a curated list in the
  admin
- THEN the API reflects the change immediately and cached responses
  invalidate (ETag changes)

#### Scenario: Import never touches curation

- WHEN an icon import (re-)runs at any ref
- THEN curated lists and memberships are unchanged

### Requirement: Read-only, cacheable serving
The icons endpoint SHALL be public, read-only, and cacheable (ETag or
equivalent); icon assets SHALL be served from media storage through the
existing symbol pipeline with long cache lifetimes. Import runs SHALL
NOT affect serving availability.

#### Scenario: Caching

- WHEN the same icons request is repeated within the cache window
- THEN the response is served from cache without recomputation

#### Scenario: Import while serving

- WHEN an import run is executing
- THEN the icons endpoint keeps serving the previously imported state
