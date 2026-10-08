## 1. Registry + import (PR A)

- [ ] 1.1 `SymbolCollection` model (slug unique, `source_org` FK,
      `TimeStampedModel`) in the symbols app + migration
- [ ] 1.2 `Icon` model: `pack` FK (required, PROTECT), `slug`,
      `UniqueConstraint(pack, slug)`, i18n `name`, `order`, `is_active`,
      `curated`, nullable indexed `unicode` (hexcode, FE0F-stripped),
      nullable `category` FK → non-root `Category`, `symbol_detailed` /
      `symbol_simple` / `symbol_mono` FKs to `Symbol` (SET_NULL);
      `Index(pack, order, slug)` + migration
- [ ] 1.3 `IconKeyword` model: `icon` FK, `locale`, `keyword`,
      `keyword_folded`; `UniqueConstraint(icon, locale, keyword_folded)`,
      `Index(locale, keyword_folded)` + migration
- [ ] 1.4 `import_emoji --ref <pin> [--noto-ref <pin>] [--locales
      de,en,fr,it]`: download pinned archives; get-or-create
      License/Organization/`SymbolCollection` packs (`fluent-emoji`,
      `noto-emoji`); write SVGs as prefixed `Symbol` rows (upstream
      styles Color→detailed, Flat→simple, High Contrast→mono; noto color
      →detailed only); upsert `Icon` rows (clean slug, hexcode, category);
      idempotent; `--dry-run` + stats; records refs/licenses
- [ ] 1.5 CLDR taxonomy get-or-create from emojibase-data
      `messages.json`: `emoji` root → groups → subgroups with localized
      `Category.i18n` names (mirror `_get_or_create_meteo_categories`)
- [ ] 1.6 Keyword import: hexcode join, folded + original keyword,
      per-locale labels; unmatched-slugs report
- [ ] 1.7 `curated` shortlist data migration (~18 activity slugs) +
      admin toggle
- [ ] 1.8 Admin: pack-scoped `Icon` list (keyword inlines, symbol slots
      with preview), `SymbolCollection` admin
- [ ] 1.9 Tests: idempotent re-run; keyword folding (accents/case);
      hexcode join coverage; asset integrity (3 styles per fluent icon,
      1 for noto); `(pack, slug)` cross-pack collision; taxonomy
      idempotency; category FK rejects roots

## 2. Search API (PR B)

- [ ] 2.1 `GET /v1/icons` — `search/lang/pack/category/curated/
      limit/offset`; ranking prefix > substring; Levenshtein ≤ 2
      fallback for terms ≥ 4 chars; stable ordering (rank, order, slug);
      `urls {detailed, simple, mono}` via `resolve_symbol_urls()`
- [ ] 2.2 Response schema: slug, pack, unicode, category, subcategory,
      curated, urls; documented in OpenAPI; additive — no version bump
      per api-versioning spec
- [ ] 2.3 ETag/Cache-Control caching; public read-only per existing
      public-endpoint pattern
- [ ] 2.4 Tests: localized ranking (zelt→tent), typo tolerance
      (montain), curated list, category pagination, pack filter, cache
      headers, locale fallback (unsupported lang → en)

## 3. Frontend switch (separate PR, frontend repo)

- [ ] 3.1 Picker searches `/v1/icons` (lang from UI locale); renders
      per-mode asset URLs; Iconify runtime kept only for legacy stored
      names
- [ ] 3.2 Legacy-name mapping command/notes for the later settings-sync
      change
