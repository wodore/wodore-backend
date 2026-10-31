## ADDED Requirements

### Requirement: Action registry model

The system SHALL provide an `ExternalAction` model in the
`external_links` app that scopes an `ExternalLink` (which owns the URL
template, i18n label and health checks) into a curated open-in action
along three axes: `kinds` (M2M to `Category` on the `map.*` kind
tree), `countries` (JSON list of ISO-3166 alpha-2 codes), and `user`
(nullable FK — NULL marks a public row, a set value a user-owned
private action) — plus `order` and `is_active`.

#### Scenario: Public action scoping
- **WHEN** a curator creates an action with `kinds=[map.transport]`,
  `countries=["CH"]`, and no user
- **THEN** the row is public, applies to transport-kind features in
  Switzerland, and participates in the public endpoint

#### Scenario: Any-point action
- **WHEN** an action has an empty `kinds` list
- **THEN** it applies to any subject, including category-less points

#### Scenario: Uniqueness
- **WHEN** a second public action references the same `ExternalLink`,
  or a user creates an action they already have for that link
- **THEN** the database rejects the duplicate (partial unique
  constraints: `UNIQUE(link) WHERE user IS NULL`,
  `UNIQUE(user, link) WHERE user IS NOT NULL`)

### Requirement: Public action list endpoint

The system SHALL expose `GET /v1/links/actions?kind=&iso=&lang=` returning
active public rows (`user IS NULL`) as an anonymous, CDN-cacheable
response. `kind` SHALL accept the kind identifier (2-slug
`Category.identifier`, unique per design) and match actions whose
`kinds` contain that identifier or whose `kinds` are empty; if `kind`
is omitted, no kind filter is applied (iso-only filtering).
`iso` SHALL match actions whose `countries` contain the code or are
empty, case-insensitively (normalized to uppercase before matching).
`lang` SHALL localize labels (the `LanguageQuery` pattern — the cache
key is the full query string). Rows SHALL include the link identifier,
i18n label, URL template and `template_vars` so clients render locally
without further requests.

#### Scenario: Country and kind filtering
- **WHEN** a client requests `?kind=map.transport&iso=CH`
- **THEN** the response contains exactly the active public actions
  matching the kind (or empty kinds) and the country (or empty
  countries), ordered by `order`

#### Scenario: Inactive rows excluded
- **WHEN** an action exists with `is_active=False` matching the filters
- **THEN** it is excluded from the response

#### Scenario: ISO case-insensitivity
- **WHEN** a client passes `iso=ch` (lowercase)
- **THEN** actions scoped to `CH` are included (the parameter is
  normalized to uppercase before matching)

#### Scenario: Localized labels
- **WHEN** a client requests `?lang=de`
- **THEN** labels are served in German (and `lang` varies the cache
  key — no cross-language cache bleed)

#### Scenario: CDN caching
- **WHEN** the endpoint is fetched twice with identical query strings
- **THEN** the response is served from the CDN edge without hitting the
  application (query-string-keyed, no auth dependency)

### Requirement: Private user actions under `/my/`

The system SHALL expose `GET /v1/my/links/actions?kind=&iso=&lang=`
that requires authentication and returns only the requesting user's
actions with the same kind/iso filtering and label localization. All
responses under the `/v1/my/` prefix SHALL carry `Cache-Control:
private, no-store` and SHALL never be CDN-cached, enforced at the
namespace level (a shared controller base class) rather than
per-view; unauthenticated requests SHALL be rejected.

#### Scenario: User sees only own actions
- **WHEN** an authenticated user requests `/v1/my/links/actions`
- **THEN** only that user's actions are returned, with private cache
  headers

#### Scenario: Anonymous rejected
- **WHEN** an unauthenticated client requests any `/v1/my/` path
- **THEN** the request is rejected with an authentication error

### Requirement: Server-side render endpoint

The system SHALL expose
`GET /v1/links/actions/{identifier}?lat=&lon=&name=&…` — `{identifier}`
IS the backing `ExternalLink.identifier` (the action model carries
none of its own). The action renders when a public action exists for
that link, OR an action owned by the requester does; otherwise the
response is 404. Rendering goes through `ExternalLink.render_url(**params)`
in the request language; missing template variables are reported as a
validation error naming the missing key(s); unknown params are
ignored.

#### Scenario: Render with feature properties
- **WHEN** a client requests the render endpoint with the clicked
  feature's `lat`, `lon` and `name`
- **THEN** the response contains the fully substituted URL in the
  request language

#### Scenario: Owner resolution
- **WHEN** a link backs only a user-owned action and the render
  endpoint is requested by another user or anonymously
- **THEN** the response is 404; for the owner (and for any link with a
  public action) it renders

### Requirement: Seed data

The system SHALL seed the registry with journey planners (SBB for CH,
DB Navigator for DE, ÖBB for AT), global map apps (Google Maps, Apple
Maps, Mapy, Organic Maps) and at least one point-weather action
(meteoblue), each backed by a template `ExternalLink` with documented
`template_vars` examples. The seed SHALL add no new category
vocabularies (the kinds axis reuses the existing `map.*` tree).

#### Scenario: Re-running the seed
- **WHEN** the seed command runs again
- **THEN** missing rows are created and no existing row is ever
  modified (additive-only `get_or_create` — curator edits are
  structurally safe)
