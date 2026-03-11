# Generated manually on 2026-03-11

import django.db.models.deletion
import django.utils.timezone
import server.core.models
from django.db import migrations, models


def populate_geoplace_categories(apps, schema_editor):
    GeoPlace = apps.get_model("geometries", "GeoPlace")
    GeoPlaceCategory = apps.get_model("geometries", "GeoPlaceCategory")
    db_alias = schema_editor.connection.alias

    batch = []
    batch_size = 1000
    place_rows = (
        GeoPlace.objects.using(db_alias)
        .exclude(place_type__isnull=True)
        .values_list("id", "place_type_id")
        .order_by("id")
        .iterator()
    )

    for place_id, category_id in place_rows:
        if category_id is None:
            continue
        batch.append(
            GeoPlaceCategory(geo_place_id=place_id, category_id=category_id)
        )
        if len(batch) >= batch_size:
            GeoPlaceCategory.objects.using(db_alias).bulk_create(
                batch, ignore_conflicts=True
            )
            batch = []

    if batch:
        GeoPlaceCategory.objects.using(db_alias).bulk_create(
            batch, ignore_conflicts=True
        )

    protected_qs = (
        GeoPlace.objects.using(db_alias)
        .filter(protected_fields__contains=["place_type"])
        .order_by("id")
    )
    for place in protected_qs.iterator():
        protected_fields = list(place.protected_fields or [])
        if "place_type" in protected_fields:
            protected_fields = [
                "categories" if field == "place_type" else field
                for field in protected_fields
            ]
            # Deduplicate while preserving order
            seen = set()
            deduped = []
            for field in protected_fields:
                if field in seen:
                    continue
                seen.add(field)
                deduped.append(field)
            place.protected_fields = deduped
            place.save(update_fields=["protected_fields"])


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0023_add_unique_source_id_constraint"),
    ]

    operations = [
        migrations.CreateModel(
            name="GeoPlaceCategory",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    server.core.models._AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    server.core.models._AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="geo_place_associations",
                        to="categories.category",
                    ),
                ),
                (
                    "classifier",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="classifications",
                        to="categories.category",
                    ),
                ),
                (
                    "extra",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Category-specific overflow data (JSON)",
                        verbose_name="Extra",
                    ),
                ),
                (
                    "geo_place",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="category_associations",
                        to="geometries.geoplace",
                    ),
                ),
            ],
            options={
                "verbose_name": "Geo Place Category Association",
                "verbose_name_plural": "Geo Place Category Associations",
                "ordering": ["geo_place", "category"],
                "db_table": "geometries_geoplace_category",
            },
        ),
        migrations.AddField(
            model_name="geoplace",
            name="categories",
            field=models.ManyToManyField(
                related_name="geo_places",
                through_fields=("geo_place", "category"),
                through="geometries.GeoPlaceCategory",
                to="categories.category",
                verbose_name="Categories",
            ),
        ),
        migrations.AddIndex(
            model_name="geoplacecategory",
            index=models.Index(
                fields=["category", "geo_place"],
                name="gpc_cat_place_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="geoplacecategory",
            index=models.Index(
                fields=["geo_place", "category"],
                name="gpc_place_cat_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="geoplacecategory",
            index=models.Index(
                fields=["classifier"],
                name="gpc_classifier_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="geoplacecategory",
            constraint=models.UniqueConstraint(
                fields=("geo_place", "category"),
                name="geoplacecategory_unique_place_category",
            ),
        ),
        migrations.RunPython(
            populate_geoplace_categories, reverse_code=migrations.RunPython.noop
        ),
        migrations.RemoveField(
            model_name="geoplace",
            name="place_type",
        ),
    ]
