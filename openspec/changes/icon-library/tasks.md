## 1. Registry + import (PR A)

- [x] 1.1 `SymbolCollection` model (slug unique, `source_org` FK,
      `TimeStampedModel`) in the symbols app + migration
- [x] 1.2 `Icon` model: `pack` FK (required, PROTECT), `slug`,
      `UniqueConstraint(pack, slug)`, i18n `name`, `order`, `is_active`,
      nullable indexed `unicode` (hexcode, FE0F-stripped),
      nullable `category` FK → non-root `Category`, `symbol_detailed` /
      `symbol_simple` / `symbol_mono` FKs to `Symbol` (SET_NULL);
      `Index(pack, order, slug)` + migration
- [x] 1.3 `IconKeyword` model: `icon` FK, `locale`, `keyword`,
      `keyword_folded`; `UniqueConstraint(icon, locale, keyword_folded)`,
      `Index(locale, keyword_folded)` + migration
- [x] 1.4 `icon_import --source <source> --ref <pin>` (pluggable
      sources in `symbols/icon_sources/`; current: `fluent`, `noto`)
      `[--locales de,en,fr,it]`: download pinned archives;
      get-or-create License/Organization/`SymbolCollection` packs
      (`fluent-emoji`, `noto-emoji`); write SVGs as prefixed `Symbol`
      rows (upstream styles Color→detailed, Flat→simple, High
      Contrast→mono; noto color→detailed only); upsert `Icon` rows
      (clean slug, hexcode, category); idempotent; `--dry-run` + stats;
      records refs/licenses
- [x] 1.5 CLDR taxonomy get-or-create from emojibase-data
      `messages.json`: `emoji` root → groups → subgroups with localized
      `Category.i18n` names (mirror `_get_or_create_meteo_categories`)
- [x] 1.6 Keyword import: hexcode join, folded + original keyword,
      per-locale labels; unmatched-slugs report
- [x] 1.7 `IconCuratedList` model (unique slug, name) with explicit
      timestamped through model (`IconCuratedListEntry`) + seeded
      `activities` list (basic activity slugs) + manual admin curation
      (entry inline with icon autocomplete); import never touches
      curation
- [x] 1.8 Admin: pack-scoped `Icon` list (keyword inlines, symbol slots
      with preview), `SymbolCollection` admin
- [x] 1.9 Tests: idempotent re-run; keyword folding (accents/case);
      hexcode join coverage; asset integrity (3 styles per fluent icon,
      1 for noto); `(pack, slug)` cross-pack collision; taxonomy
      idempotency; category FK rejects roots

## 2. Search API (PR B)

- [x] 2.1 `GET /v1/icons` — `search/lang/pack/category/list/
      limit/offset`; ranking prefix > substring; Levenshtein ≤ 2
      fallback for terms ≥ 4 chars; stable ordering (rank, order, slug);
      `urls {detailed, simple, mono}` via `resolve_symbol_urls()`
- [x] 2.2 Response schema: slug, pack, unicode, category, subcategory,
      lists, urls; documented in OpenAPI; additive — no version bump
      per api-versioning spec
- [x] 2.3 ETag/Cache-Control caching; public read-only per existing
      public-endpoint pattern
- [x] 2.4 Tests: localized ranking (zelt→tent), typo tolerance
      (montain), curated list, category pagination, pack filter, cache
      headers, locale fallback (unsupported lang → en)

## 3. Frontend switch (separate PR, frontend repo)

- [ ] 3.1 Picker searches `/v1/icons` (lang from UI locale); renders
      per-mode asset URLs; Iconify runtime kept only for legacy stored
      names
- [ ] 3.2 Legacy-name mapping command/notes for the later settings-sync
      change
