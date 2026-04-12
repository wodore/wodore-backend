## 1. Setup

- [x] 1.1 Add `factory_boy` to dev dependencies in pyproject.toml
- [x] 1.2 Create `tests/seed/` directory and empty `tests/seed/__init__.py`

## 2. Factory Definitions

- [x] 2.1 Create `tests/factories.py` with `HutFactory` — random name, Swiss Point location (SRID 4326), default category for hut_type_open, country CH, is_active=True
- [x] 2.2 Add `GeoPlaceFactory` — random name, Swiss Point location, linked category, is_active=True
- [x] 2.3 Add `ContactFactory` — random name, linked ContactFunction (uses existing from fixtures or creates one)
- [x] 2.4 Add `AvailabilityFactory` — linked Hut and Organization, auto-calculated occupancy_percent/occupancy_steps/occupancy_status from free and total values
- [x] 2.5 Add `OwnerFactory` and any supporting factories needed for Hut FK relations

## 3. Export Commands

- [x] 3.1 Create `server/apps/huts/management/commands/test_export_huts.py` — export huts with name, location (SRID=4326 POINT), elevation, country, hut_type slugs, capacity, org associations (slug + source_id), contacts (function slug, name, email, phone)
- [x] 3.2 Add CLI options to `test_export_huts`: `--limit N`, `--sort random|alpha|elevation`, `--out FILE`, `--include-inactive`
- [x] 3.3 Create `server/apps/geometries/management/commands/test_export_geoplaces.py` — export geoplaces with name, location, elevation, country, category slugs, importance, detail_type
- [x] 3.4 Add CLI options to `test_export_geoplaces`: `--limit N`, `--sort random|alpha|elevation`, `--out FILE`

## 4. Seed Data Infrastructure

- [x] 4.1 Define seed YAML format and create initial `tests/seed/huts.yaml` with ~10 huts (generated from dev DB via export command or manually crafted)
- [x] 4.2 Create seed loader function in `tests/seed/loader.py` — reads YAML files, creates model instances (Hut, GeoPlace) with relations (orgs, contacts, categories), slug auto-generated on save
- [x] 4.3 Add session-scoped pytest fixture in `tests/conftest.py` — calls seed loader, detects if seeding is needed (Hut.objects.exists() check), skips if data already present

## 5. Validation

- [x] 5.1 Verify seed fixture works: run pytest with `--create-db` and confirm data loads
- [x] 5.2 Verify `--reuse-db`: run pytest again and confirm seeding is skipped, tests see seed data
- [x] 5.3 Verify transaction rollback: write a quick test that deletes a seeded hut, assert it's gone, then assert it's back in a separate test
- [x] 5.4 Verify export commands: run `test_export_huts --limit 5 --sort random` and confirm valid YAML output
