"""Shared hut relation annotations for the list and detail endpoints.

Both endpoints aggregate sources (JSONBAgg) and images with subtly
different projections; the duplication had already drifted
(image_url only in list, review_status/no_publication only in detail).
This module is the single place those differences live.
"""

from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models import F, Value
from django.db.models.functions import Coalesce, Concat, JSONObject


def _license_fields(*, detail: bool = False):
    if detail:
        return dict(
            slug="image_set__license__slug",
            is_active="image_set__license__is_active",
            name=Coalesce("image_set__license__name_i18n", "image_set__license__slug"),
            fullname=Coalesce(
                "image_set__license__fullname_i18n",
                "image_set__license__name_i18n",
                "image_set__license__slug",
            ),
            description="image_set__license__description_i18n",
            url="image_set__license__url_i18n",
            no_publication="image_set__license__no_publication",
        )
    return dict(
        slug="image_set__license__slug",
        name="image_set__license__name_i18n",
        fullname="image_set__license__fullname_i18n",
        description="image_set__license__description_i18n",
        url="image_set__license__url_i18n",
    )


def annotate_hut_sources(*, media_url: str, detail: bool = False):
    """Sources aggregation shared by get_huts and get_hut.

    detail=True adds active/order (the detail endpoint sorts by order);
    list omits them for payload size.
    """
    fields = dict(
        logo=Concat(Value(media_url), F("org_set__logo")),
        fullname="org_set__fullname_i18n",
        slug="org_set__slug",
        name="org_set__name_i18n",
        link="orgs_source__link",
        source_id="orgs_source__source_id",
        public="org_set__is_public",
    )
    if detail:
        fields.update(
            active="org_set__is_active",
            order="org_set__order",
        )
    return JSONBAgg(JSONObject(**fields), distinct=True)


def annotate_hut_images(*, media_url: str = "", detail: bool = False):
    """Images aggregation. detail adds review_status and license flags."""
    extra = {}
    if not detail:
        extra["image_url"] = Concat(Value(media_url), F("image_set__image"))
    else:
        extra["review_status"] = "image_set__review_status"

    return JSONBAgg(
        JSONObject(
            image="image_set__image",
            image_meta=JSONObject(
                crop="image_set__image_meta__crop",
                focal="image_set__image_meta__focal",
                width="image_set__image_meta__width",
                height="image_set__image_meta__height",
            ),
            caption="image_set__caption_i18n",
            license=JSONObject(**_license_fields(detail=detail)),
            author="image_set__author",
            author_url="image_set__author_url",
            source_url="image_set__source_url",
            organization=JSONObject(
                logo=Concat(Value(media_url), F("image_set__source_org__logo")),
                fullname="image_set__source_org__fullname_i18n",
                slug="image_set__source_org__slug",
                name="image_set__source_org__name_i18n",
                url="image_set__source_org__url",
            ),
            attribution=Value(""),
            **extra,
        ),
        # Django 6 renamed the aggregate-ordering kwarg from ``ordering``
        # to ``order_by``; the old name is silently dropped (see the
        # availability geojson for the same regression).
        order_by=(
            F("image_set__details__score").desc(nulls_last=True),
            "image_set__details__id",
        ),
    )
