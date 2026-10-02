## Why

Two response-narrowing vocabularies coexist: JSON:API sparse fieldsets
(`fields[TYPE]=a,b`, 7 endpoints) and `include_X=no|slug|all`
(64 IncludeModeEnum fields across search/nearby/amenity/meteo/huts-search).
`include_sources=slug` and `fields[sources]=slug` express the same concept;
harmonizing on the JSON:API convention removes a parallel concept.

## What Changes

- All `include_X` query parameters replaced by `fields[TYPE]` sparse fieldsets
- The tri-state `no|slug|all` maps to fieldset selection:
  - `no` → field absent from the parent selection
  - `slug` → parent field present, nested type narrowed to slug
  - `all` → parent field present, nested type un-narrowed
- Breaking change: registers a new API version; include_X senders get 400

## Capabilities

### Modified Capabilities
- `sparse-fieldsets`: extended to cover the former include_X endpoints
