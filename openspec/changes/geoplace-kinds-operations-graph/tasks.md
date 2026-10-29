# Tasks: geoplace-kinds-operations-graph

> Supersedes draft PR #154's openspec. Advisor review round 3
> applied (tiles-capacity mirror, place-level validation mechanism,
> pinned kind mapping + exclusions, capacity-key retirement, parent
> cleanup spots, MonthAccessor, read-default pin).
> Migration approach: GeoPlace data is disposable (drop + re-import)
> — phases exist for review order, not dual-write windows.
> Prerequisite: PR #446 merged as-is.

## 1. Kinds & protected vocabulary

- [ ] 1.1 `PLACE_KINDS` registry (`geometries/kinds.py`): pinned
      mapping from the spec (root slug → detail_type + allowed
      classifiers), vocabulary-root exclusion set, default kind,
      `kind_for(category)` with the `(order, slug)` tie-break; test:
      registry values ⊆ detail_type CHECK constraint set, every live
      root resolves (or is excluded)
- [ ] 1.2 `Category.is_protected` field + migration; seed marks
      mode.*, role.*, relations.*, root kind parents, uri-kind roots;
      admin blocks deletion of protected rows (presentation editable)
- [ ] 1.3 `detail_type` derived on write: populate from
      `kind_for(first category)` in `_create_from_schema` /
      `_update_from_schema` and admin save; remove detail_type
      declaration from input schemas and OSM config (including the
      docstring's bogus "accommodation" value)
- [ ] 1.4 Validation: classifier subtree ∈ kind's allowed set
      (extends `validate_attributes`); admin classifier autocomplete
      scoped to the allowed subtrees (replaces the hardcoded
      `mode` scope)
- [ ] 1.5 Tests: registry coverage over the live root tree,
      classifier rejection (mode on groceries), tie-break determinism,
      vocabulary-root exclusion, protected deletion blocked / rename
      allowed, detail_type derivation

## 2. Operations, seasonality & place-level extra

- [ ] 2.1 `GeoPlaceOperation` model: `(geo_place, mode)` unique,
      `capacity` int ≥ 0 CHECK, `opening_hours` JSON, `extra` JSONB,
      RESTRICT mode FK; migration + factories; per-mode capacity
      invariant test (same-mode associations share one capacity)
- [ ] 2.2 `GeoPlaceSeasonality` model: OneToOne, `month_01…month_12`
      int NULL CHECK 0–100; `Month` IntEnum + `MonthAccessor`
      (ported from #154: TypeError non-Month keys, ValueError range,
      to_dict round-trip); migration + factories
- [ ] 2.3 Schema write path: operation + seasonality upserts in
      `GeoPlace.update_or_create` (protected-fields policy applies;
      share < 100 with no reduced type resolves to
      accommodation.unknown — explicit or implicit); capacity removed
      from association-extra writes **and the accommodation
      CategoryExtraSchema seed loses the `capacity` key** (no second
      home)
- [ ] 2.4 Wodore import retarget (explicit sub-items, GO-review):
      (a) capacities → operation rows per mode
      (`GeoPlaceOperation(mode, capacity)`);
      (b) `open_monthly` → seasonality via the fuzzy mapping
      (yes=100, yesish=75, maybe=50, noish=25, no=0, unknown=NULL);
      (c) months below 100 with **no reduced type** resolve the
      reduced mode to `accommodation.unknown` (association
      materialized or implicit — design D4, PO confirmed);
      (d) scope: the wodore (hut) handler only — geonames writes
      neither operations nor seasonality
- [ ] 2.5 OSM import retarget: opening_hours → operation row
      (standard mode); months where present → seasonality
- [ ] 2.6 Place-level extra validation: `resolve_extra_schema`
      place-level resolution (kind root parent, explicit-row
      override) wired into model save/clean, schema upsert, admin
      save — same metaschema/fail-open guardrails; admin renders
      `GeoPlace.extra` via the JSON-Schema widget with the kind
      schema. Seed kind schemas: `administrative`
      (population/postal_code/iso_code), groceries/sport
      opening-hours (requiredness per kind)
- [ ] 2.7 Tests: operation uniqueness + CHECK constraints, per-mode
      hours, seasonality range checks + accessor, fuzzy mapping,
      closed-semantics scenario, place-level extra validation,
      import end-to-end, idempotent re-import

## 3. Relation graph

- [ ] 3.1 `relations/*` vocabulary seed (part_of, near, serves,
      access_point) + protected marking
- [ ] 3.2 `GeoPlaceRelation` model: unique triple, no self-loops
      (both scenario-tested), confidence + extra, composite indexes,
      `limit_choices_to` relations subtree; migration + factories
- [ ] 3.3 `GeoPlace.add_relation` / `get_related_places` helpers
      (direction-aware, idempotent)
- [ ] 3.4 `GeoPlace.parent` removal: idempotent `parent → part_of`
      data migration, field removal, cleanup of the named spots —
      `providers/base.py` `select_related("parent")`,
      `_track_field_modifications` simple_fields entry, input-schema
      `parent_id` drop (API changelog note); no output payload
      referenced parent (verified)
- [ ] 3.5 Relation auto-generation as a standalone management
      command (`generate_place_relations --types part_of,serves`, GO
      review: cheaper than an import hook — same end-state):
      containment → part_of, proximity → serves; confidence < 1.0;
      idempotent re-runs (same triple replaced, curated edges
      preserved); bounded to configured types; configurable
      thresholds; run post-import
- [ ] 3.6 Tests: constraints (incl. self-loop), helpers, reverse
      traversal, auto-generation idempotence, parent migration
      fidelity

## 4. Detail retirement & readers

- [ ] 4.1 API amenity block served from operation rows + place extra
      (wire shape unchanged, `operating_status` reads default `open`
      — contract tests before/after)
- [ ] 4.2 Admin: operation + seasonality inlines on GeoPlace;
      admin-detail scalars → place extra editing via the kind schema
- [ ] 4.3 Delete AmenityDetail + AdminDetail (models, schemas,
      imports, admin, tests)
- [ ] 4.4 Booking: document + test the attribution trio
      (uri.booking link, source association, party role.source);
      derived `is_bookable` helper
- [ ] 4.5 Tiles: capacity stays tile-visible — join operation rows
      per mode into the categories JSON (or feature-level property);
      regenerate `martin_sync`; seasonality join evaluated for
      availability Phase D only (out of scope here)

## 5. Verification & docs

- [ ] 5.1 Drop + full re-import on the lane DB (OSM sample + wodore);
      count/spot-check report (places, operations, seasonality,
      relations, tile capacity)
- [ ] 5.2 Full suite + `pyrefly check` + `makemigrations --check`
- [ ] 5.3 Work doc under `_work/`; openspec validation
      (`openspec validate`); PR #154 closed as superseded with a
      pointing comment
