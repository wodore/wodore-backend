# icon-search-multi-pack

## 1. Server

- [x] 1.1 `IconsQuery.pack` accepts comma-separated slugs (description
  documents both forms)
- [x] 1.2 `_facet_base` filters `pack__slug__in` on the parsed slug list
      (whitespace-tolerant, empty segments dropped)
- [x] 1.3 ETag cache key verified to include the raw `pack` value

## 2. Tests

- [x] 2.1 Multi-pack facet returns the union of the given packs
- [x] 2.2 Whitespace tolerance and unknown-slug tolerance
- [x] 2.3 Multi-pack combines with `search` like the single-pack facet
