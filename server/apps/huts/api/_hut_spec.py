"""Reader pairs for the hut detail query (OpenSpec phase 2 pilot).

get_hut's wire schema (HutSchemaDetails) cannot drive a fully derived
spec: its hut-type ``symbol`` field is resolved by a request-context
validator (absolute URLs), ``edit_link``/``modified`` are view-injected,
and the translated attributes need the modeltrans ``i18n`` column —
narrowing the query to the wire schema's field set would starve them.

This module therefore applies the reader-pair pattern to what the
endpoint actually is: one optimized query — four joins plus four
aggregates — expressed as composable ``(prepare, project)`` pairs.
pydantic ``from_attributes`` remains the projector (that is the
architectural decision from the adopt-django-readers design: the wire
schema is the serialization source of truth; readers owns the query).

Full ``spec_from_schema`` derivation lands on the simpler cold schemas
(categories, organizations) in phase 3.
"""

from collections.abc import Callable

from django.db.models import QuerySet

from .annotations import annotate_hut_images, annotate_hut_sources

# A django-readers-style reader pair half: (queryset) -> queryset.
Prepare = Callable[[QuerySet], QuerySet]

# Relations joined in the single detail query.
DETAIL_JOINS = (
    "hut_owner",
    "hut_type_open",
    "hut_type_closed",
    "availability_source_ref",
)


def select_related_pair(*relations: str) -> tuple[Prepare, None]:
    """Join the given relations in the main query (to-one)."""

    def prepare(queryset: QuerySet) -> QuerySet:
        return queryset.select_related(*relations)

    return prepare, None


def annotate_pair(
    **annotations: object,
) -> tuple[Prepare, None]:
    """Attach the given annotation expressions in the main query."""

    def prepare(queryset: QuerySet) -> QuerySet:
        return queryset.annotate(**annotations)

    return prepare, None


def translations_annotation():
    """Per-language name/description map (wire field ``translations``)."""
    from django.db.models.functions import JSONObject

    return JSONObject(
        description=JSONObject(
            de="description_de",
            en="description_en",
            fr="description_fr",
            it="description_it",
        ),
        name=JSONObject(
            de="name_de",
            en="name_en",
            fr="name_fr",
            it="name_it",
        ),
    )


def has_availability_annotation():
    """True when the hut references an availability source."""
    from django.db.models import Case, Value, When

    return Case(
        When(availability_source_ref__isnull=False, then=Value(True)),
        default=Value(False),
    )


def prepare_hut_detail(queryset: QuerySet, *, media_url: str) -> QuerySet:
    """The full hut-detail query: four joins + four aggregates, one pass.

    Same SQL shape as the pre-readers implementation (joins instead of
    prefetches, aggregates in the main query) — pinned by the
    query-count test; see tasks.md 2.2.
    """
    from django.db.models import F

    join_prepare, _ = select_related_pair(*DETAIL_JOINS)
    aggregates_prepare, _ = annotate_pair(
        has_availability=has_availability_annotation(),
        availability_source_ref__slug=F("availability_source_ref__slug"),
        sources=annotate_hut_sources(media_url=media_url, detail=True),
        images=annotate_hut_images(detail=True),
        translations=translations_annotation(),
    )

    queryset = join_prepare(queryset)
    return aggregates_prepare(queryset)
