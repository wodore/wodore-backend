# Tasks: geoplace-parties

## 1. Party model, links & role vocabulary

- [x] 1.1 Data migration creating the `role` parent category with
      children `operator`, `brand`, `source` (active, ordered,
      slug-stable; idempotent rerun; `owner` dropped from the seed —
      operator covers owning-or-operating per OSM semantics)
- [x] 1.2 Create `parties` app: `Party` (slug unique, `name` i18n via
      modeltrans, `note` i18n optional, `is_active`, `is_public`,
      `review_status`, optional `symbol_color`/`symbol_mono` FKs) +
      `PartyLink` through model (order) to `ExternalLink`; migrations,
      admin (Unfold, TABS entry, symbol pickers), `__str__`, factories
      (models/admin shipped with the app scaffold in #165; factories
      added with the association work)
- [x] 1.3 `GeoPlaceParty` in geometries: role FK → Category, unique
      `(geo_place, party, role)`, RESTRICT on party and role FKs,
      `order`, indexes; `clean()` role-subtree validation mirrored in
      the schema write path; unit tests for constraints and validation
      (schema-write mirroring lands with the import tasks 2.x/3.x)

## 2. Brand replacement

- [x] 2.1 Data migration: for every `AmenityDetail` with `brand`,
      get_or_create Party (slug from category slug, name from category
      i18n) + association role `role.brand`; idempotent (0053: convert
      + FK removal in one migration, reverse is column-restore noop)
- [x] 2.2 Remove `AmenityDetail.brand` FK (+ `amenity_brands`
      related_name), the admin autocomplete scoping, and `BrandInput`;
      replace with `PartyInput` (slug, name, role identifier) in the
      input schema; update `AmenityDetail.update_or_create` to write
      the association instead of the FK (shared
      `_write_party_associations` helper also drives the GeoPlace-level
      create/update schema paths; dedup matches brand-party
      associations instead of the FK; the brand category LRU cache and
      `_get_brand_category_by_slug` are gone)
- [x] 2.3 OSM import: `brand` tag → Party(role `role.brand`,
      get_or_create by slug); `operator` tag → Party(role
      `role.operator`, review status `review`, single values only);
      drop `_get_or_create_brand_category`; import tests (both precache
      paths pre-mint parties — operators first, into review;
      `_get_or_create_brand_organization` brand→Organization minting
      also removed; write-path tests pin the schema contract the
      import drives)

## 3. Owner merge & hut import

- [x] 3.1 `import_parties` management command: Owner → Party by slug
      (name/note i18n, url → ExternalLink), `--dry-run`, idempotent
      re-runs; tests (shared `parties.services.merge_owner`; new links
      get an explicit label + skip_health_check so the merge never
      does network I/O)
- [x] 3.2 Extend the wodore hut import to write party associations
      from `hut_owner` (role `role.operator`); import test
      (`_ensure_hut_party` on create + on unprotected updates; merges
      the owner on the fly so a prior `import_parties` run is not
      required; the capacity change's schema-path rewrite keeps the
      same helper)

## 4. API & admin

- [ ] 4.1 Add `parties` (`[{role, slug, name, links, symbol}]`, symbol
      as resolved color/mono URLs, same helper pattern as category
      symbols) to GeoPlace responses under `fields[places]`, nested
      `fields[parties]` narrowing; changelog entry per `api-conventions`;
      schema + response tests
- [ ] 4.2 Party admin + GeoPlace party inline (party autocomplete, role
      autocomplete scoped to `role.*`); inline save marks
      `is_modified`/`protected_fields`; amenity admin brand-free; admin
      tests

## 5. Verification

- [ ] 5.1 Lane-DB dry-runs: data migrations (role vocabulary, brand
      counts before/after), `import_parties --dry-run`, OSM sample
      import, wodore hut import
- [ ] 5.2 Full test suite (`scripts/lane-run.sh .venv/bin/pytest`) and
      work doc under `_work/`
