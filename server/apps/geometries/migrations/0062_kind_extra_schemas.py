"""Update kind-root extra schemas (task 2.3 + 2.6).

- ``accommodation``: the association-level schema drops the
  ``capacity`` key — capacity lives on ``GeoPlaceOperation`` rows now;
  the row stays (empty properties) as the admin-editable home for
  future association attributes.
- ``administrative``: gains the place-level schema for the folded
  AdminDetail scalars (``population``, ``postal_code``, ``iso_code``)
  — validated on every place-extra write path.

Idempotent: plain update_or_create, safe to re-run.
"""

from typing import Any

from django.db import migrations

ACCOMMODATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}

ADMINISTRATIVE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "population": {
            "type": ["integer", "null"],
            "minimum": 0,
            "title": "Population",
        },
        "postal_code": {
            "type": ["string", "null"],
            "title": "Postal code",
        },
        "iso_code": {
            "type": ["string", "null"],
            "title": "ISO code",
        },
    },
    "additionalProperties": True,
}


def seed(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    CategoryExtraSchema = apps.get_model("geometries", "CategoryExtraSchema")

    for root_slug, schema in (
        ("accommodation", ACCOMMODATION_SCHEMA),
        ("administrative", ADMINISTRATIVE_SCHEMA),
    ):
        root = Category.objects.filter(slug=root_slug, parent__isnull=True).first()
        if root is None:
            continue
        CategoryExtraSchema.objects.update_or_create(
            category=root, defaults={"schema": schema}
        )


def unseed(apps: Any, _schema_editor: Any) -> None:
    CategoryExtraSchema = apps.get_model("geometries", "CategoryExtraSchema")
    CategoryExtraSchema.objects.filter(
        category__slug__in=["accommodation", "administrative"],
        category__parent__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0022_category_is_protected"),
        ("geometries", "0061_geoplace_operation_seasonality"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
