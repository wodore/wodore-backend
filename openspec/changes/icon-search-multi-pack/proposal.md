## Why

With flag packs (`flag-icons`, `circle-flags`, waved `noto-emoji` flags)
imported alongside the emoji packs, clients want to search a *set* of packs
in one request — e.g. "fluent-emoji plus the flag packs" — instead of firing
one request per pack and stitching client-side. The `pack` facet today
accepts exactly one slug.

## What Changes

- `GET /v1/icons` `pack` parameter accepts a single pack slug (unchanged)
  **or** a comma-separated list of pack slugs, filtering to the union of the
  given packs. Whitespace around slugs is tolerated; unknown slugs
  contribute nothing (facet semantics, not a validation error).
- No schema, model, import, or ranking changes — the facet only widens the
  candidate set, and the ETag cache key already derives from the raw query
  value.
- Additive API change: optional-parameter semantics, no contract version
  bump (docs/api-versioning.md rules).
