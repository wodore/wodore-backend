# Spec Delta: external-link-uris

## ADDED Requirements

### Requirement: URI-kind category vocabulary
The system SHALL provide a `uri` parent category with children `uri.phone` (scheme `tel:`), `uri.email` (scheme `mailto:`) and `uri.website` (schemes `http:`/`https:`), created by data migration and manageable in the category admin. Each URI-kind category SHALL carry its accepted URL scheme(s) and a health-check policy flag as category metadata (`extra`) and MAY carry curated Symbol icons (color and mono). This URI dimension SHALL be independent of the existing loose `link_type` purposes (`website`, `osm_edit`, `reservation`, …), which remain unchanged. Additional URI kinds MAY be added later via migration and spec delta without code changes.

#### Scenario: Vocabulary exists after migrate

- **WHEN** migrations run on a fresh database
- **THEN** the `uri.phone`, `uri.email` and `uri.website` categories exist, are active, and carry their accepted schemes and health-check policy in `extra` (`uri.phone`/`uri.email` not health-checked, `uri.website` health-checked)

#### Scenario: A new URI kind needs no code change

- **WHEN** an admin adds a `uri.fax` child (scheme `fax:`, not health-checked) via migration + admin
- **THEN** links can be classified `uri.fax` and validated against its schemes without any application-code change

#### Scenario: URI dimension is orthogonal to link purpose

- **WHEN** a link has `link_type` purpose `reservation` and URI kind `uri.phone`
- **THEN** both classifications are retained independently — the purpose vocabulary is untouched by the URI dimension

### Requirement: Scheme-aware link URL storage
`ExternalLink.url` SHALL store URLs for any scheme accepted by its URI kind — `http`, `https`, `tel` or `mailto` — replacing the http(s)-only `URLField` with a character field validated by scheme-specific validators, and SHALL carry a `uri_kind` foreign key to a category under the `uri` parent on every row: a data migration backfills the existing http(s) links to `uri.website` first, then an `AlterField` makes the column NOT NULL (backfill first, constraint second). All per-language i18n URL variants SHALL be validated by the same scheme rules. A `tel:` or `mailto:` URL that the former `URLField` rejected at the field layer SHALL now be storable.

#### Scenario: A phone URI is storable

- **WHEN** an `ExternalLink` is saved with `uri_kind=uri.phone` and `url="tel:+4233702323"`
- **THEN** the save succeeds (the scheme-aware field accepts `tel:`), whereas the former `URLField` would have rejected it

#### Scenario: Every link carries a URI kind

- **WHEN** the backfill and NOT NULL migrations run against production data
- **THEN** the backfill assigns `uri.website` to every existing http(s) link, the NOT NULL constraint succeeds, and subsequent saves without a URI kind are rejected

#### Scenario: A malformed URI is rejected

- **WHEN** an `ExternalLink` is saved with a URL whose scheme is unsupported or whose value is malformed for its scheme (e.g. a bare phone number with no `tel:` scheme)
- **THEN** the save is rejected with a validation error

### Requirement: URI kind derived from the URL
The system SHALL derive an `ExternalLink`'s `uri_kind` automatically from the URL: when a URL value is entered or changed, the model save path SHALL set or update `uri_kind` to the vocabulary kind whose accepted schemes contain the URL's scheme — no manual pick is needed, and admin forms, imports and schema write paths are covered uniformly by this one derivation step (no separate endpoint or signal). A URL whose scheme matches no vocabulary kind SHALL be rejected with a validation error. Manual override SHALL remain possible only within the chosen kind's accepted schemes.

#### Scenario: Entering a phone URL derives the kind

- **WHEN** an `ExternalLink` is saved with `url="tel:+4137123456"` and no kind manually chosen
- **THEN** `uri_kind` is set to `uri.phone` automatically

#### Scenario: Changing the URL re-derives the kind

- **WHEN** a `uri.phone` link's URL is changed to `https://example.org` and saved
- **THEN** `uri_kind` is re-derived to `uri.website`

#### Scenario: Unknown scheme is rejected

- **WHEN** a link is saved with `url="ftp://example.org/file"` and no vocabulary kind accepts `ftp`
- **THEN** the save is rejected with a validation error

#### Scenario: Manual override stays within the kind's schemes

- **WHEN** an admin explicitly sets `uri_kind=uri.website` on a link whose URL is `https://example.org`
- **THEN** the explicit kind is respected (its schemes contain the URL's scheme)

### Requirement: Scheme and URI-kind consistency validation
An `ExternalLink` SHALL validate, in `clean()` and in every schema/import write path, that each populated URL's scheme is among its URI kind's accepted schemes — `tel:` ⇔ `uri.phone`, `mailto:` ⇔ `uri.email`, `http(s)` ⇔ `uri.website` — and that the URI is well-formed for that scheme; a link whose kind's accepted schemes exclude a populated URL's scheme SHALL be rejected with a validation error. The web-only auto-behaviours in `save()` — source-organization detection, title extraction and health checking — SHALL run only for `http`/`https` URLs, so saving a `tel:` or `mailto:` link performs no network I/O.

#### Scenario: Scheme mismatched to kind is rejected

- **WHEN** an `ExternalLink` with `uri_kind=uri.phone` is saved with an `http://…` URL (or a `uri.website` link with a `tel:` URL)
- **THEN** `clean()` (and the schema/import write path) rejects it with a validation error

#### Scenario: Consistent link passes

- **WHEN** an `ExternalLink` with `uri_kind=uri.email` is saved with `url="mailto:info@example.org"`
- **THEN** validation passes and the link is stored

#### Scenario: Non-web save does no network I/O

- **WHEN** a `tel:` link is saved
- **THEN** no source auto-detection, title extraction or HTTP health check is performed

### Requirement: Per-URI-kind health-check policy
Link health checking SHALL be governed per URI kind: web links (`uri.website` / http(s)) are HTTP-checked as today (updating `last_checked`, `response_code`, `failure_count` and the review-status transitions), while non-web kinds (`tel:`, `mailto:`) are exempt and SHALL NOT be network-checked. The health-check selector SHALL skip exempt kinds, the per-link `run_health_check` flag SHALL remain an override, and the existing `response_code_valid` check constraint SHALL continue to hold (exempt links keep `response_code` null).

#### Scenario: Web link is checked

- **WHEN** the health-check selector runs over a `uri.website` link
- **THEN** it issues the HTTP check and updates `last_checked`/`response_code`/`failure_count` as today

#### Scenario: Phone link is exempt

- **WHEN** the health-check selector runs over a `uri.phone` (or `uri.email`) link
- **THEN** the link is skipped — no network request is made, `response_code` stays null, and it is not transitioned to review for a "failure"

#### Scenario: Response-code constraint still holds

- **WHEN** an exempt `tel:` link is stored with `response_code` null
- **THEN** the `response_code_valid` constraint is satisfied

### Requirement: Phone normalization to E.164 and migration to typed links
Phone numbers SHALL be normalized to international E.164 form (`+<countrycode><number>`) using the `phonenumbers` library when creating `tel:` links, defaulting the region from the place's `country_code` for national numbers. A data migration SHALL convert every `AmenityDetail.phones` JSON entry into a `uri.phone` `ExternalLink` (normalized E.164 URL, label preserved, health check disabled) and a `GeoPlaceExternalLink` association to the amenity's place, idempotently, thereby also populating the previously-empty place-links table. Unparseable numbers SHALL be recorded for review, not silently dropped.

#### Scenario: Phone JSON migrates to a typed link

- **WHEN** the data migration processes an `AmenityDetail` with `phones=[{"number": "+423 370 23 23", "label": null}]`
- **THEN** a `uri.phone` `ExternalLink` with `url="tel:+4233702323"` exists and is associated to the detail's place via `GeoPlaceExternalLink`

#### Scenario: Migration is idempotent

- **WHEN** the phone data migration runs a second time
- **THEN** no duplicate links or associations are created (get_or_create keyed on the normalized URL and place)

#### Scenario: Unparseable number is flagged, not dropped

- **WHEN** a phone entry cannot be parsed into E.164
- **THEN** it is recorded for review (and/or logged by the migration) rather than discarded, so no data is lost

### Requirement: Place links exposed on the detail response
The GeoPlace detail response (`place-detail-api`, merged in PR #418) SHALL include a `links` member — an ordered list of the place's associated external links as `[{uri, url, label, symbol}]`, where `uri` is the URI-kind identifier (e.g. `uri.phone`), `url` the localized URL, `label` the localized label, and `symbol` the resolved color/mono URLs of the URI kind — as an optional member under the `fields[places]` sparse-fieldset selection, a sibling of `categories`, `sources` and `parties`, with nested narrowing via `fields[links]`. Only active, public, review-`done` links SHALL be surfaced, and database work SHALL be skipped when the member is not selected. Because `place-detail-api` is merged (the `fields[places]` allowlist and its unknown-field-name rule live on main), this change SHALL add the `links` member to the merged `GeoPlaceDetailSchema` additively — it becomes a valid `fields[places]` name with no other contract change. The additive change SHALL be registered in the API changelog automatically at release (label-driven, no manual entry).

#### Scenario: Detail carries links

- **WHEN** a client fetches a place that has a `uri.phone` link, with `links` selected
- **THEN** the response contains `links: [{uri: "uri.phone", url: "tel:+4233702323", label, symbol}]` with `symbol` present when the URI kind has icons

#### Scenario: Narrowed selection skips link queries

- **WHEN** a client sends `?fields[places]=slug,name` (omitting `links`)
- **THEN** the response has no `links` member and the link prefetch is not executed

#### Scenario: Only public, done links surface

- **WHEN** a place has one review-`done` public link and one `new`/non-public link
- **THEN** the `links` member contains only the review-`done` public link

### Requirement: Amenity block phones member retired
The `amenity` detail block SHALL no longer expose the `phones` member; phone numbers SHALL be served exclusively as `uri.phone` entries of the place `links` member. Removing `phones` is a breaking response change and SHALL be amended into the current unreleased API version (never stacked) per the `api-versioning` runbook, with a regenerated committed snapshot and the `api:breaking` label; the geo surface is pre-release with zero consumers, so the sunset window is 0 and no downgrade transform is required (the same doctrine as the `place-detail-endpoint` slug-only transition). The `AmenityDetail.phones` column SHALL be retained for one release for rollback and removed in a later cleanup.

#### Scenario: Amenity response has no phones member

- **WHEN** a client fetches an amenity place after this change ships
- **THEN** the `amenity` block contains `operating_status`, `opening_months` and `opening_hours` but no `phones` member

#### Scenario: Phones are served under links

- **WHEN** a client fetches an amenity place that previously exposed `amenity.phones`, with `links` selected
- **THEN** the phone numbers appear as `uri.phone` entries in the `links` member

#### Scenario: Breaking removal registered per the runbook

- **WHEN** the PR is labeled `api:breaking`
- **THEN** the registry's unreleased `VersionChange` documents the amenity `phones` removal, and the committed OpenAPI snapshot matches the registry
