# Tasks: harmonize-narrowing-vocabularies

## 1. Mapping design
- [ ] Document the include_X → fields[TYPE] mapping per endpoint
- [ ] Decide the TYPE names for nested types (hut_types, categories, symbols, collections)

## 2. Backend
- [ ] search_huts: include_hut_type/include_sources → fields[hut_types]/fields[sources]
- [ ] search_geoplaces/nearby_geoplaces: include_categories/include_sources → fields[places]/fields[categories]/fields[sources]
- [ ] get_amenity: include_sources → fields[sources]
- [ ] get_weather_codes/get_weather_code: include_symbols/category/collection → fields[symbols]/fields[categories]/fields[collections]
- [ ] Remove IncludeModeEnum (or keep as internal implementation detail)
- [ ] New VersionChange; regenerate snapshots

## 3. Frontend
- [ ] Regenerate types; update all include_X call sites to fields[TYPE]
- [ ] Use Sparse<T, K> for the narrowed views
