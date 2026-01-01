# Future Improvements & TODOs

This document tracks potential improvements, refactoring ideas, and technical debt that should be addressed in future iterations.

## Project-Wide Improvements

### 1. Terminology Refactoring: "Open/Closed" → "Standard/Reduced"

**Priority:** Medium  
**Effort:** High (Major project-wide refactoring)

**Current state:** The system uses "open/closed" terminology throughout the project:
- **Hut model:** `hut_type_open` / `hut_type_closed`, `capacity_open` / `capacity_closed`
- **Availability app:** All logic and queries reference open/closed states
- **Booking logic:** External service integration uses open/closed concepts
- **External packages:** `hut-services` and potentially `hut-services-private` may need updates

**Problem:** The terms "open" and "closed" are misleading because:
- A hut in "closed" state isn't necessarily closed - it may be unattended or in winter mode
- The states represent operational modes, not whether the hut is accessible
- Real-world example: A hut can be unattended in summer and fully closed in winter
- Confusing for API consumers and frontend developers

**Proposed refactoring:** Rename to "standard/reduced" terminology:
- `hut_type_standard` / `hut_type_reduced`
- `capacity_standard` / `capacity_reduced`

**Benefits:**
- **More accurate** - Reflects that these are different operational modes with different capacities
- **Flexible** - Works for any dual-state scenario (attended/unattended, summer/winter, full/partial)
- **Clear** - "Standard" implies normal operation, "reduced" implies limited capacity/services
- **Better API** - More intuitive for API consumers

**Impact:** This is a major refactoring that would affect:

**Backend (wodore-backend):**
- Database schema (model fields, migrations)
- Hut model in `server/apps/huts/models/_hut.py`
- Availability service in `server/apps/availability/services.py`
- Booking API endpoints in `server/apps/huts/api/_booking.py`
- Admin interfaces for Huts and Availability
- Django Ninja API schemas
- External integrations reading these fields

**External packages:**
- `hut-services` - May need schema updates if it exposes these concepts
- `hut-services-private` - Likely needs updates for consistency

**Frontend/API consumers:**
- Any existing API clients will need updates
- Consider API versioning or backward compatibility layer

**Alternative terminology considered:**
- `normal/reduced`
- `full/limited`
- `primary/secondary`
- `peak/off_peak`

**Implementation steps:**
1. **Phase 1: External packages (if needed)**
   - Review `hut-services` and `hut-services-private` for references
   - Update schemas and enums if necessary
   - Publish new package versions

2. **Phase 2: Database migration**
   - Create Django migration to rename fields in Hut model
   - Create migration for any foreign key references
   - Test migration on staging database

3. **Phase 3: Backend code**
   - Update all model references in `server/apps/huts/models/_hut.py`
   - Update `server/apps/availability/services.py` logic and comments
   - Update `server/apps/huts/api/_booking.py` API endpoints
   - Update booking schemas in `server/apps/huts/schemas_booking/`
   - Update admin interfaces
   - Search codebase for any remaining "open"/"closed" references

4. **Phase 4: API compatibility**
   - Decide on API versioning strategy
   - Add backward compatibility if needed
   - Update API documentation

5. **Phase 5: Testing & Documentation**
   - Update all documentation (README, CLAUDE.md, etc.)
   - Update tests
   - Deploy to staging and verify

**Risks:**
- Breaking changes for existing API consumers
- Complex migration if data is referenced externally
- Potential downtime during migration

---

## Availability App

### 2. Generator-based External Fetching

**Priority:** Low  
**Effort:** Medium

**Current limitation:** All huts are fetched and returned as a complete list before processing begins. For very large batches, this can cause memory issues and delays the start of database updates.

**Proposed improvement:** Refactor `hut-services-private` to use a generator pattern:

```python
# Future: Generator yields results as they're fetched
for hut_result in service.get_bookings_generator(
    hut_slugs=slugs,
    request_interval=0.1
):
    # Process and store each hut immediately
    process_hut_bookings(hut_result)
    progress_callback()
```

**Benefits:**
- **Streaming processing** - Start storing data while still fetching remaining huts
- **Lower memory usage** - Don't hold all results in memory at once
- **Better progress granularity** - Progress updates happen as each hut is fetched
- **Request interval stays in external service** - Rate limiting remains where it belongs

**Implementation notes:**
- Modify `hut-services-private` to yield `HutBookingsSchema` objects one at a time
- Rate limiting (`request_interval`) stays in the external service between yields
- Progress callback gets called after each yield in the availability service
- Maintains clean separation of concerns (external fetching vs. database storage)

---

### 3. Other Availability Enhancements

**Priority:** Low  
**Effort:** Varies

- Add API endpoints (Django Ninja) for querying availability
- Add trend analysis endpoints
- Implement async task queue (Celery) for large batch updates
- Add parallel service calls when multiple external services are available
- Add data retention policies for old history entries

---

## General TODOs

_Add other project-wide improvements here as they are identified_
