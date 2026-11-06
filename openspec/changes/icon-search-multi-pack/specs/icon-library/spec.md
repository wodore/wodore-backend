## MODIFIED Requirements

### Requirement: Searchable icons endpoint
The system SHALL expose `GET /v1/icons` with `search`, `lang`, `pack`,
`category`, `list`, `limit`, and `offset` parameters. The `pack` parameter
SHALL accept a single pack slug or a comma-separated list of pack slugs,
filtering to the union of the given packs; whitespace around slugs SHALL be
tolerated and unknown slugs SHALL contribute no icons. Search SHALL
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

#### Scenario: Multi pack filter

- WHEN `pack=fluent-emoji,flag-icons` (optionally with whitespace
  around the slugs)
- THEN only icons of those two packs are returned, in the endpoint's
  normal ranking and stable sort order

#### Scenario: Unknown pack in a multi pack filter

- WHEN `pack=noto-emoji,nope`
- THEN only icons of `noto-emoji` are returned (unknown slugs contribute
  nothing; no error is raised)

#### Scenario: Curated list

- WHEN `list=activities` with no search term
- THEN that curated list is returned (the seeded basic activity
  shortlist by default; further lists are managed in the admin)
