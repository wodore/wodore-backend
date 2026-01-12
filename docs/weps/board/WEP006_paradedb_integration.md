---
draft: false
date:
  created: 2025-01-12
  updated: 2025-01-12
slug: wep006
categories:
  - WEP
tags:
  - wep006
  - search
  - postgresql
---

# `WEP 6` ParadeDB Integration for Advanced Search

Integrating ParadeDB to provide Elasticsearch-quality full-text search with BM25 ranking while maintaining native PostGIS integration for geographic queries.
<!-- more -->

## Requirements

* **Improved search relevance** using BM25 ranking algorithm (Elasticsearch-quality)
* **Multi-language fuzzy search** across all translations with better performance
* **Native PostGIS integration** for combined text + geographic queries in single SQL
* **Zero synchronization overhead** - search directly on operational data
* **Minimal infrastructure changes** - prefer extension over additional services
* **Backward compatibility** - maintain existing API contracts

## Current State Analysis

### Existing Search Implementation

**Current Approach**:
* Trigram similarity via `pg_trgm` for fuzzy matching
* Multi-language support using JSONB `i18n` field
* Complex scoring combining similarity, importance, prefix match, token match, and FTS rank
* Deduplication using PostGIS for near-identical places
* Separate endpoint for nearby queries

**Performance Characteristics**:
* Trigram search performance degrades with dataset size
* Multiple similarity calculations across all languages
* ~75+ lines of complex annotation logic
* Multiple GIN indexes required (full-text + trigrams)

**Strengths**:
* Good multi-language fuzzy matching
* Sophisticated composite ranking
* Smart deduplication logic
* Clean Django ORM integration

**Weaknesses**:
* Complex query logic (hard to maintain)
* Performance degrades with large datasets
* No true BM25 ranking (only `ts_rank`)
* Index sprawl (multiple GIN indexes)
* Manual similarity score calculation

## Proposed Solution

### ParadeDB Overview

ParadeDB is a PostgreSQL extension built on Tantivy (Rust search library) that provides:

* **BM25 full-text search** (same algorithm as Elasticsearch)
* **164x faster fuzzy search** than `pg_trgm` in benchmarks
* **Zero ETL** - search directly on PostgreSQL data
* **ACID compliant** - maintains transactional consistency

**Key Features**:
* BM25 ranking with global corpus statistics
* Fuzzy search via Levenshtein distance (edit distance)
* Phrase matching, boolean queries, prefix matching
* Field-specific search with boosting
* **JSONB field indexing** (perfect for our `i18n` structure)
* Hybrid search support (BM25 + semantic vectors)

### Why ParadeDB Over Alternatives

| Solution | BM25 | PostGIS Integration | Multi-Language | Infrastructure | Effort |
|----------|------|---------------------|----------------|----------------|--------|
| **ParadeDB** | ✅ Yes | ✅ Native | ✅ JSONB support | Extension only | 6-12h |
| **Meilisearch** | ✅ Yes | ❌ Separate | ⚠️ Multiple indexes | New service | 24-48h |
| **Elasticsearch** | ✅ Yes | ❌ Separate | ⚠️ Complex | New cluster | 40-80h |
| **Optimize PG** | ❌ ts_rank only | ✅ Native | ⚠️ Manual | No changes | 8-16h |

**ParadeDB Wins For**:
* Native PostGIS integration (single query combining text + geo)
* Works with our existing JSONB structure
* No additional services or synchronization
* Fastest implementation time
* True BM25 ranking quality

## Technical Architecture

### Docker Deployment Strategy

Two options available, each with trade-offs:

### Option A: ParadeDB Docker Image (Recommended) ✅

Use `paradedb/paradedb:pg16-postgis-3.4-alpine` image

**Advantages**:
* Pre-built extension (already compiled and tested)
* PostGIS 3.4 included
* Zero compilation or build dependencies
* Official support from ParadeDB team
* Simple upgrade path (change image tag)

**Disadvantages**:
* Different base image than current `postgis/postgis`
* Slightly larger image size
* Requires data migration to new container

**Migration Process**:
1. Backup existing data with `pg_dump`
2. Switch to ParadeDB image
3. Restore with `psql`
4. Verify extension installation

**Migration Effort**: ~30 minutes for data migration + testing

### Option B: Manual Extension Installation

Install `pg_search` extension in existing `postgis/postgis:16-3.4-alpine` image

**Advantages**:
* Keep current image (no container migration)
* Familiar base image
* No data migration

**Disadvantages**:
* Compilation required (Rust toolchain in container)
* Complex build process
* Compatibility risk (extension version must match PostgreSQL minor version)
* Maintenance burden (manual rebuilds for updates)
* No official support

**Why Not Recommended**:
* ParadeDB compilation is complex and error-prone
* Alpine compatibility issues with Rust
* ~30-60 minutes additional build time
* Harder to reproduce across environments

### Recommendation: **Option A (ParadeDB Docker Image)** ✅

**Rationale**:
* Official ParadeDB images are well-tested and optimized
* Includes PostGIS 3.4 (same version we use)
* Simple 5-minute change vs complex compilation
* ParadeDB team maintains compatibility
* Data migration is straightforward

### Django Integration

**Package**: `paradedb-django` (v1.2.0 on PyPI)

#### Model Configuration

Add BM25 index to existing model:

```python
# Add BM25Index to model's Meta
Bm25Index(
    fields=["id", "name", "i18n", "importance", "country_code"],
    json_fields=[
        JSONFieldIndexConfig("i18n", fast=True)
    ]
)
```

#### API Query Updates

**Before** (complex, 75+ lines):
```python
# Multiple TrigramSimilarity calculations
# Complex score annotations
# Manual similarity thresholds
```

**After** (simplified):
```python
# Search across requested language
queryset.filter(
    JsonOp("i18n", "name_{lang}", "match", value=query) |
    Search("name", query)
)
```

### Multi-Language Search with JSONB

**How It Works**:
* ParadeDB automatically indexes all JSONB keys
* Our `i18n` field stores translations like: `{"name_en": "Matterhorn", "name_de": "Matterhorn", "name_fr": "Cervin"}`
* Fast field configuration enables efficient JSONB queries

**Search Patterns**:

```python
# Single language search
filter(JsonOp("i18n", "name_de", "match", value="Matterhorn"))

# Multi-language fallback
filter(
    JsonOp("i18n", "name_de", "match", value=query) |
    JsonOp("i18n", "name_fr", "match", value=query) |
    Search("name", query)
)
```

### PostGIS Integration

**Key Advantage**: ParadeDB works seamlessly with PostGIS in a single query

```python
# Combined: BM25 text search + geographic distance + importance
filter(
    Search("name", query),
    location__distance_lte=(point, D(km=10))
).annotate(
    distance=Distance("location", point)
).order_by("distance", "-importance")
```

## Implementation Plan

### Phase 1: Setup (2 hours)

**Tasks**:
1. Update docker-compose.yml with ParadeDB image
2. Backup existing PostgreSQL data
3. Start ParadeDB container
4. Verify extension installation
5. Install `paradedb-django` package

### Phase 2: Integration (4-6 hours)

**Tasks**:
1. Add BM25Index to GeoPlace model
2. Create migration
3. Update search endpoint
4. Update nearby endpoint (if needed)
5. Add helper functions for multi-language search

### Phase 3: Testing (4 hours)

**Unit Tests**:
* Basic search functionality
* Multi-language search
* Fuzzy matching
* Combined PostGIS queries
* Edge cases (empty queries, special characters)

**Integration Tests**:
* Verify all existing endpoints return same results
* Check response format unchanged
* Validate filtering (type, category, country, importance)
* Test pagination

**Performance Tests**:
* Benchmark current vs ParadeDB
* Measure query latency
* Check index usage

### Phase 4: Deployment (2 hours)

**Staging**:
1. Deploy to staging environment
2. Run full test suite
3. Load test with production-like data
4. Monitor query performance
5. Compare with current implementation

**Production**:
1. Schedule maintenance window
2. Backup production database
3. Deploy ParadeDB container
4. Run migrations
5. Verify API responses
6. Monitor error rates and performance

## Performance Comparison

### Expected Improvements

| Metric | Current (Trigram) | ParadeDB (BM25) | Improvement |
|--------|------------------|-----------------|-------------|
| **Fuzzy search** | ~500-1000ms | ~100-200ms | **5x faster** |
| **Full-text search** | ~200-400ms | ~50-100ms | **4x faster** |
| **Multi-language** | Multiple queries | Single query | **Simpler** |
| **Code complexity** | 75+ lines | ~20 lines | **4x simpler** |
| **Index count** | 3-5 GIN indexes | 1 BM25 index | **Simpler** |

### Benchmark Data Source

Based on ParadeDB official benchmarks (2024):
* **Fuzzy search**: 164x faster than `pg_trgm` (22.8s → 139ms)
* **Full-text search**: 4.4x faster than native PostgreSQL (401ms → 92ms)
* **Field-specific search**: 48x faster (4.4s → 90ms)

**Our Use Case**:
* Moderate dataset (~100K places)
* Multi-language queries
* PostGIS integration
* Expected: 3-5x overall improvement

## Rollback Strategy

### If Issues Arise

**Immediate Rollback** (< 5 minutes):
```bash
# Stop ParadeDB
docker-compose down

# Revert docker-compose.yml
git checkout HEAD -- docker-compose.yml

# Restart PostGIS
docker-compose up -d db

# Restore from backup if needed
```

**Code Rollback**:
* Remove migrations
* Remove package
* Revert API and model changes

### Data Safety

* No data migration required (BM25 index is separate)
* Original data untouched
* Trigram indexes remain intact
* Can run both implementations in parallel for testing

## Migration Timeline

### Total Effort: **12-16 hours**

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| **Phase 1: Setup** | 2 hours | None |
| **Phase 2: Integration** | 4-6 hours | Phase 1 complete |
| **Phase 3: Testing** | 4 hours | Phase 2 complete |
| **Phase 4: Deployment** | 2 hours | Phase 3 complete |

### Milestones

1. **Milestone 1**: ParadeDB running with extension verified (Day 1, 2h)
2. **Milestone 2**: BM25 index created (Day 1, 6h)
3. **Milestone 3**: Search endpoint updated (Day 2, 10h)
4. **Milestone 4**: Tests passing (Day 2, 14h)
5. **Milestone 5**: Deployed to staging (Day 3, 16h)

## Risks and Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Data migration issues** | High | Low | Test backup/restore in staging first |
| **Extension compatibility** | Medium | Low | Use official ParadeDB image (tested) |
| **Performance regression** | High | Low | Benchmark in staging before production |
| **API incompatibility** | Medium | Low | Comprehensive integration tests |
| **Learning curve** | Low | Medium | Team training on ParadeDB syntax |

## Success Criteria

### Functional Requirements

* All existing search functionality works
* Multi-language search operational
* PostGIS integration maintained
* API responses unchanged
* Backward compatible with existing clients

### Performance Requirements

* 95th percentile query latency < 200ms
* Index-only scans for common queries
* No increase in database CPU usage
* Index size < 20% of data size

### Quality Requirements

* All tests passing
* No regressions in search relevance
* Clean code review approval
* Documentation updated

## Future Considerations

### Phase 2 Enhancements (Optional)

* **Semantic Search**: Integrate `pgvector` for vector embeddings
* **Hybrid Search**: Combine BM25 + semantic with RRF (Reciprocal Rank Fusion)
* **Autocomplete**: Implement suggestive search with prefix queries
* **Search Analytics**: Track query patterns for optimization
* **Synonyms**: Add synonym support for common place name variants

### Scalability

* **Vertical scaling**: ParadeDB scales to millions of documents
* **Read replicas**: Can use read replicas for search-heavy workloads
* **Caching**: Add Redis for frequent search queries
* **Materialized views**: Pre-compute common search patterns

## Conclusion

ParadeDB provides a compelling upgrade to our current search implementation:

* **Better relevance** through true BM25 ranking
* **Faster queries** with 3-5x performance improvement
* **Simpler code** reducing complexity by 4x
* **Native PostGIS integration** maintaining our geo capabilities
* **Zero synchronization** overhead with direct data access
* **Low implementation effort** (12-16 hours vs 40-80h for Elasticsearch)

The recommended approach uses the official ParadeDB Docker image, which includes PostGIS and requires only a straightforward data migration. This minimizes risk while providing significant improvements to search quality and performance.

**Recommendation**: Proceed with Phase 1 (Setup) as proof-of-concept, with full rollout upon successful testing.
