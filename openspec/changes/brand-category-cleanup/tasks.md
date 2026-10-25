# Tasks: brand-category-cleanup

## 1. Cleanup migration

- [x] 1.1 Data migration (geometries): delete `GeoPlaceCategory` rows
      whose category is a child of `root.brand`, then delete the
      `root.brand` parent (children cascade); lookup by identifier,
      idempotent, no-op reverse
- [x] 1.2 Unit test: seed a legacy `root.brand` subtree with a place
      association + an unrelated category vocabulary; assert
      associations/subtree removed, unrelated categories and party
      associations survive; fresh-database no-op covered by the
      migration running in every test setup
- [x] 1.3 Lane-DB dry-run (`scripts/lane-run.sh .venv/bin/python
      manage.py migrate --plan` + live run with counts), full suite,
      pyrefly/ruff, work doc under `_work/`
