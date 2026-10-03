## 1. Registry + import (PR A)

- [ ] 1.1 `EmojiIcon` model (slug unique, hexcode + index, group, subgroup, curated bool, svg_color/svg_flat/svg_high_contrast paths, upstream_ref, sort_key) + `EmojiIconKeyword` (icon FK, locale, keyword, keyword_folded; unique (icon, locale, keyword_folded), index (locale, keyword_folded)) + migrations
- [ ] 1.2 `import_fluent_emoji --ref <pin> [--noto-ref <pin>] [--locales de,en,fr,it]` — download pinned archives, write style SVGs (fluent: 3 styles; noto: color) to static storage, import metadata with `family` (fluent | noto); idempotent upserts; record refs/licenses
- [ ] 1.3 Keyword import from emojibase-data (pinned version): hexcode join, folded + original keyword, per-locale labels; unmatched-slugs report
- [ ] 1.4 `curated` shortlist management (data migration with the ~18 activity slugs; admin toggle)
- [ ] 1.5 Tests: idempotent re-run, keyword folding (accents/case), hexcode join coverage report, asset integrity (3 styles per icon)

## 2. Search API (PR B)

- [ ] 2.1 `GET /v1/icons` — search/lang/style/category/curated/limit/offset; ranking prefix > substring; Levenshtein ≤ 2 fallback for terms ≥ 4 chars; stable ordering (rank, sort_key)
- [ ] 2.2 Response schema: slug, unicode, group, subgroup, curated, urls {color, flat, high_contrast}; documented in OpenAPI + version bump per api-versioning spec
- [ ] 2.3 ETag/Cache-Control caching; public read-only (no auth) per existing public-endpoint pattern
- [ ] 2.4 Tests: localized ranking (zelt→tent), typo tolerance (montain), curated list, category pagination, cache headers, locale fallback (unsupported lang → en)

## 3. Frontend switch (separate PR, frontend repo)

- [ ] 3.1 Picker searches `/v1/icons` (lang from UI locale); renders backend asset URLs per visual mode; Iconify runtime kept only for legacy stored names
- [ ] 3.2 Legacy-name mapping command/notes for the later settings-sync change
