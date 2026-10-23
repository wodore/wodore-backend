# Tasks: geoplace-operators

## 1. Operator model & app

- [ ] 1.1 Create `operators` app: `Operator` (slug unique, `name` i18n
      via modeltrans, `note` i18n optional, `is_active`, `is_public`,
      `review_status` per design lean) + `OperatorLink` through model
      (order) to `ExternalLink`; migrations, admin (Unfold, TABS entry),
      `__str__`, factories
- [ ] 1.2 `GeoPlaceOperatorAssociation` in geometries: role
      TextChoices (`operator`, `brand`), unique
      `(geo_place, operator, role)`, DB check constraint on role,
      `order`, indexes; unit tests for constraints

## 2. Brand replacement

- [ ] 2.1 Data migration: for every `AmenityDetail` with `brand`,
      get_or_create Operator (slug from category slug, name from
      category i18n) + association role `brand`; idempotent
- [ ] 2.2 Remove `AmenityDetail.brand` FK (+ `amenity_brands`
      related_name), the admin autocomplete scoping, and `BrandInput`;
      replace with `OperatorInput` (slug, name, role) in the input
      schema; update `AmenityDetail.update_or_create` to write the
      association instead of the FK
- [ ] 2.3 OSM import: `brand` tag → Operator(role `brand`,
      get_or_create by slug, review flag per design); `operator` tag →
      Operator(role `operator`, single values only); drop
      `_get_or_create_brand_category`; import tests

## 3. Owner merge & hut import

- [ ] 3.1 `import_operators` management command: Owner → Operator by
      slug (name/note i18n, url → ExternalLink), `--dry-run`, idempotent
      re-runs; tests
- [ ] 3.2 Extend the wodore hut import (schema-path rewrite from the
      capacity change) to write operator associations from `hut_owner`
      (role `operator`); import test

## 4. API & admin

- [ ] 4.1 Add `operators` (`[{role, slug, name, links}]`) to GeoPlace
      responses under `fields[places]`, nested `fields[operators]`
      narrowing; changelog entry per `api-conventions`; schema +
      response tests
- [ ] 4.2 Operator admin + GeoPlace operator inline (role + autocomplete);
      inline save marks `is_modified`/`protected_fields`; amenity admin
      brand-free; admin tests

## 5. Verification

- [ ] 5.1 Lane-DB dry-runs: data migration (brand counts before/after),
      `import_operators --dry-run`, OSM sample import, wodore hut import
- [ ] 5.2 Full test suite (`scripts/lane-run.sh .venv/bin/pytest`) and
      work doc under `_work/`
