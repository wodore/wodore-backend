# Proposal: external-link-uris

## Why

`ExternalLink` was built for one kind of destination: a web page.
`ExternalLink.url` is a `URLField` (Django validates `http`/`https`
only — `tel:` and `mailto:` are rejected at the field layer), the
`save()`/health-check machinery assumes an HTTP endpoint it can `HEAD`,
and the only typed dimension (`link_type` → Category) is a *loose
purpose* (`website`, `osm_edit`, `reservation`, …), not a transport
kind. So a phone number or an e-mail address has no home as a link.

Meanwhile contact data is already in the system in the wrong shape.
58,064 of 391,300 `AmenityDetail` rows carry phones as raw JSON
(`[{"number": "+423 370 23 23", "label": null}]`), and the OSM import
splits websites into `ExternalLink` entities but phones into
`AmenityDetail.phones`. Phones-as-JSON cannot be health-policy'd,
cannot carry an icon, cannot be deduplicated across places, and sit on
the amenity detail block — invisible to every non-amenity place and to
the shared link machinery. The unified place detail endpoint
(`place-detail-endpoint`, merged in PR #418) serves them on the
`amenity` block, which is the moment to retire that member cleanly:
the geo surface is pre-release with zero consumers, so the contact
story can be fixed in one breaking stroke the same way the slug-only
transition was.

The owner decision: make links carry **typed URIs**. A phone is a
`tel:` link, an e-mail a `mailto:` link, a web page an `http(s)` link —
all first-class `ExternalLink` rows classified by a new, admin-
extensible **URI-kind** category dimension (with icons), validated for
scheme ↔ kind consistency, health-checked only where it makes sense,
and exposed on every place through a single `links` response member.

## What Changes

- **New `uri` category vocabulary** (a second, independent dimension
  alongside the untouched loose `link_type` purposes): a migration-
  seeded `uri` parent with children `uri.phone` (`tel:`), `uri.email`
  (`mailto:`) and `uri.website` (`http(s)`), following the `role.*`
  vocabulary pattern from `geoplace-parties`. Each URI-kind category
  carries its accepted URL scheme(s) and health-check policy as
  category metadata (`extra`) and curated Symbol icons (color + mono) —
  **not an enum**, so kinds stay admin-extensible (`uri.fax` → `fax:`
  needs no code change).
- **`ExternalLink.url` becomes scheme-aware**: the http(s)-only
  `URLField` is replaced by a character field with scheme-specific
  validators that accept `http`, `https`, `tel` and `mailto` (all
  per-language i18n URL variants validated identically). A `uri_kind`
  FK → Category (scoped to the `uri` parent) classifies the link's
  transport and is required on every row: the existing http(s) links
  are backfilled to `uri.website`, then an `AlterField` makes the
  column NOT NULL — backfill first, constraint second, the slug-
  invariant migration pattern from `place-detail-endpoint`.
- **Derived URI kind + proper save check**: the model save path
  derives `uri_kind` from the entered or changed URL — the vocabulary
  kind whose accepted schemes contain the URL's scheme — so no manual
  pick is needed and no separate endpoint or signal exists (admin
  forms, imports and schema write paths are covered uniformly). An
  unknown scheme rejects the save; manual override stays possible
  within the kind's accepted schemes. `ExternalLink.clean()` (and
  every schema/import write path) validates that each URL's scheme
  matches its URI kind — `tel:` ⇔ `uri.phone`, `mailto:` ⇔
  `uri.email`, `http(s)` ⇔ `uri.website` — plus URI well-formedness.
  `save()`'s web-only auto-behaviours (title extraction,
  source-organization detection, health check) run only for http(s)
  URLs.
- **Per-URI-kind health-check policy**: web links are HTTP-checked as
  today; `tel:`/`mailto:` links are exempt and never network-checked.
  The health-check selector, the per-link `run_health_check` override
  and the existing `response_code_valid` constraint all respect the
  exemption (exempt links keep `response_code` null).
- **Phones normalize to E.164** (`+<country><number>`) via the
  `phonenumbers` library and migrate out of JSON: a data migration
  converts the 58k `AmenityDetail.phones` entries into `uri.phone`
  `ExternalLink` rows plus `GeoPlaceExternalLink` associations to the
  amenity's place — which also populates the currently-empty place-
  links table.
- **New `links` member on the place detail response**:
  `[{uri, url, label, symbol}]`, a `fields[places]`-selectable sibling
  of `categories`/`sources`/`parties` (per `place-detail-api`), with
  nested narrowing via `fields[links]`.
- **The amenity block's `phones` member retires** (breaking): phones
  are served only through `links` as `uri.phone` entries. Amended into
  the current *unreleased* API version per `docs/api-versioning.md`
  (no consumer exists; sunset window 0; same doctrine as PR #418);
  changelogs are label-driven (`api:*`, `type:*`) — never manual.

## Capabilities

### New Capabilities

- `external-link-uris`: Requirements for the `uri` category
  vocabulary (schemes + health policy + icons as metadata), the
  scheme-aware `ExternalLink.url` storage and `uri_kind` dimension, the
  scheme ↔ kind consistency validation, the per-kind health-check
  policy, E.164 phone normalization and the JSON-phones data migration,
  the `links` place-detail response member, and the breaking retirement
  of the amenity `phones` member.

### Modified Capabilities

(none — `place-detail-api` ships in `place-detail-endpoint`
(merged, PR #418) but is not yet an archived baseline spec, so its
contract cannot be a `MODIFIED` delta here. The `links` member and
the `phones` retirement are expressed as `ADDED` requirements in this
capability and add to the merged `GeoPlaceDetailSchema`
additively, exactly as `geoplace-parties` added its `parties` member
rather than modifying the place detail spec. The loose `link_type`
purposes are unchanged.)

## Impact

- **`server/apps/external_links/`** — `ExternalLink.url`
  URLField → scheme-aware CharField + validators; new `uri_kind` FK
  with save-path scheme derivation; `clean()` scheme/kind consistency;
  `save()` web-only gating; health-check selector respects the kind
  policy; migrations (field swap, `uri_kind` FK, backfill of the
  existing http(s) links to `uri.website`, then `AlterField` to NOT
  NULL).
- **`server/apps/categories/`** — `uri` parent + children data
  migration (schemes + health policy in `extra`, symbols), mirroring
  the `role.*` seed.
- **`server/apps/symbols/`** — curated phone/mail/link SVGs sourced via
  the Iconify agent (Material Symbols / Lucide) and imported through the
  symbols pipeline; wired to the URI-kind categories' `symbol_color`/
  `symbol_mono`.
- **`server/apps/geometries/`** —
  `presenters.py` (`prefetch_links` + `build_links_data`),
  `schemas/_output.py` (`LinkSchema`, `links` on `GeoPlaceDetailSchema`;
  drop `phones` from `AmenityDetailSchema` and the amenity input),
  `models/_amenity_detail.py` (stop writing `phones`; drop it from
  `_trackable_fields`), `api.py` (`field_selected` gating for `links`),
  and the data migration converting `AmenityDetail.phones` →
  `uri.phone` links + `GeoPlaceExternalLink`.
- **`server/apps/apiversions/registry.py`** — amend the *unreleased*
  `VersionChange` (document the amenity `phones` removal); regenerate
  and commit the snapshot.
- **Dependencies** — `phonenumbers` (new); `pyproject.toml`/lockfile.
- **Dependency assumptions** — builds on the merged
  `place-detail-endpoint` (PR #418: the `fields[places]` detail
  response and the `amenity` block the `links` member joins and the
  `phones` member leaves) and reuses `geoplace-parties`'
  link-serialization shape; no huts-app changes.
- **Non-goals** — attaching the existing ~34k website `ExternalLink`
  entities to places (that is OSM-import wiring, tracked separately —
  the `links` member surfaces whatever associations exist); dropping the
  `AmenityDetail.phones` column immediately (kept one release for
  rollback, removed in a later cleanup, per the brand-subtree doctrine);
  converting `link_type` purposes into the URI dimension; Jinja2 link
  templating (owned by the Organization convergence).
