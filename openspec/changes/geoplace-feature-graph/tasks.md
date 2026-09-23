## 1. Foundations (renames first — strict order)

- [ ] 1.1 Create `_work` → openspec reference: this change replaces `_work/260313_geoplace_feature_graph_spec.md` and `_work/260313_feature_graph_implementation.md` (delete both files in this branch once artifacts are complete)
- [ ] 1.2 Rename `GeoPlaceCategory.classifier` → `relation` (`geometries/models/_associations.py`), makemigrations `rename_geoplacecategory_classifier_to_relation`, apply
- [ ] 1.3 Rename `ExternalLink.link_type` → `relation` (`external_links/models.py`), makemigrations `rename_externallink_link_type_to_relation`, apply; update `external_links/admin.py` labels/search
- [ ] 1.4 Create `relation_categories` fixture: `relations/` (part_of, near, serves, access_point), `operating/` (standard, reduced), `link_types/` (website, booking, social, phone), `brand/`; get-or-create semantics keyed on slug (reconciles with admin-created categories in existing DBs); verify idempotent loaddata

## 2. New models

- [ ] 2.1 `geometries/models/_operation.py`: `Month` IntEnum (1-based) + `MonthAccessor` (TypeError on non-Month key, ValueError outside 0–100, `to_dict()`)
- [ ] 2.2 `GeoPlaceOperation` model in `_operation.py`: nullable capacity, month_01–12 (0–100 validated), hours string, extra JSONB, unique (geo_place, relation), indexes on (geo_place, relation), month_07, month_12; makemigrations `create_geoplaceoperation`
- [ ] 2.3 `GeoPlaceRelation` model in `_associations.py`: from/to FKs (outgoing/incoming_relations), relation FK limited to `relations/` children, confidence, extra, is_active; unique triple + no-self-loop constraints; composite indexes;
- [ ] 2.4 Update `geometries/models/__init__.py` exports (GeoPlaceRelation, GeoPlaceOperation, Month); remove AmenityDetail imports
- [ ] 2.5 GeoPlace helpers: `add_relation` (update_or_create, idempotent) and `get_related_places(relation_slug, direction)` in `_geoplace.py`

## 3. Code reference updates (17 files per implementation plan)

- [ ] 3.1 `geometries/schemas/_output.py`: AmenityDetailSchema → GeoPlaceOperationSchema (capacity, months dict, hours, extra)
- [ ] 3.2 `geometries/schemas/_input.py` + `schemas/__init__.py`: OperatingStatus imports, field types, exports
- [ ] 3.3 `geometries/api.py`: amenity filtering/serialization → operations (incl. month-percentage filters)
- [ ] 3.4 `geoplaces_import_osm.py`: AmenityDetailInput → GeoPlaceOperationInput; opening_hours/brand extraction via Month enum; brand category handling; relation auto-generation (containment → part_of, proximity → serves, operator tag → brand) with confidence
- [ ] 3.5 `test_import_performance.py`: replace AmenityDetail usage
- [ ] 3.6 `geometries/admin/_geoplace.py` and `geometries/models/_admin_detail.py`: remove AmenityDetail (incl. its admin detail mixin), register GeoPlaceRelation/GeoPlaceOperation inlines or admins (repo admin conventions: unfold, limit_choices_to, autocomplete)
- [ ] 3.7 Grep-verify zero stale references: `AmenityDetail`, `.classifier`, `.link_type`, `GeoPlace.parent`

## 4. Data migrations & removals

- [ ] 4.1 `migrate_parent_to_relations` command: GeoPlace.parent → part_of relations (idempotent); verify counts
- [ ] 4.2 Remove `GeoPlace.parent` field; makemigrations `remove_geoplace_parent`
- [ ] 4.3 `migrate_amenity_to_operation` command: AmenityDetail → GeoPlaceOperation with fuzzy mapping (no=0, noish=25, maybe=50, yesish=75, yes=100, unknown=NULL)
- [ ] 4.4 Delete `AmenityDetail` model (`_amenity_detail.py` file); makemigrations `delete_amenitydetail`

## 5. Verification & docs

- [ ] 5.1 Tests: models (constraints, MonthAccessor round-trip/errors), helpers (add_relation idempotency, direction lookup), fixtures idempotency, month-percentage query, auto-relation regeneration (re-import replaces auto edges, preserves curated); run `inv tests`
- [ ] 5.2 Verification shell checks from the implementation plan (relation/operation counts, Month values, accessor) + OSM import smoke on a sample region
- [ ] 5.3 Update `_work` log for this change; document API BREAKING renames (classifier/link_type, AmenityDetail schema) for frontend coordination
- [ ] 5.4 Open PR (this branch), reference this change, note migration-order requirements for deployment
