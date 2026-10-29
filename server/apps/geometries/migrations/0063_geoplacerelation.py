from typing import Any

import pgtrigger.compiler
import pgtrigger.migrations

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models
from django.db.models import Case, Value, When

import server.core.models


def seed_relations(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")

    parent, _created = Category.objects.get_or_create(
        slug="relations",
        parent=None,
        defaults={
            "name": "Beziehungen",
            "i18n": {"name_en": "Relations"},
            "order": 50,
            "is_active": True,
        },
    )
    for slug, name, name_en, order in [
        ("part_of", "Teil von", "Part of", 10),
        ("near", "Nahe", "Near", 20),
        ("serves", "Bedient", "Serves", 30),
        ("access_point", "Zugangspunkt", "Access point", 40),
    ]:
        Category.objects.get_or_create(
            slug=slug,
            parent=parent,
            defaults={
                "name": name,
                "i18n": {"name_en": name_en},
                "order": order,
                "is_active": True,
            },
        )

    slugs = ["part_of", "near", "serves", "access_point"]
    Category.objects.filter(pk=parent.pk).update(
        identifier="root.relations", is_protected=True
    )
    Category.objects.filter(parent=parent, slug__in=slugs).update(
        identifier=Case(
            *[When(slug=slug, then=Value(f"relations.{slug}")) for slug in slugs]
        ),
        is_protected=True,
    )


def unseed_relations(apps: Any, _schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    Category.objects.filter(
        slug__in=["part_of", "near", "serves", "access_point"],
        parent__slug="relations",
    ).delete()
    Category.objects.filter(slug="relations", parent=None).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0022_category_is_protected"),
        ("geometries", "0062_kind_extra_schemas"),
    ]

    operations = [
        migrations.CreateModel(
            name="GeoPlaceRelation",
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
                    "confidence",
                    models.FloatField(
                        default=1.0,
                        help_text="1.0 = curated; < 1.0 = auto-generated, replaced on re-runs",
                    ),
                ),
                (
                    "extra",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Overflow data for this edge (JSON)",
                    ),
                ),
                (
                    "from_place",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="outgoing_relations",
                        to="geometries.geoplace",
                        verbose_name="From place",
                    ),
                ),
                (
                    "relation",
                    models.ForeignKey(
                        help_text="Edge type (relations.* category)",
                        limit_choices_to={"parent__slug": "relations"},
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="place_relations",
                        to="categories.category",
                        verbose_name="Relation",
                    ),
                ),
                (
                    "to_place",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="incoming_relations",
                        to="geometries.geoplace",
                        verbose_name="To place",
                    ),
                ),
            ],
            options={
                "verbose_name": "Geo Place Relation",
                "verbose_name_plural": "Geo Place Relations",
                "ordering": ["from_place", "relation__order", "to_place"],
                "indexes": [
                    models.Index(
                        fields=["from_place", "relation"], name="gpr_from_relation_idx"
                    ),
                    models.Index(
                        fields=["to_place", "relation"], name="gpr_to_relation_idx"
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("from_place", "to_place", "relation"),
                        name="geoplacerelation_unique_triple",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("from_place", models.F("to_place")), _negated=True
                        ),
                        name="geometries_geoplacerelation_no_self_loops",
                    ),
                ],
            },
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="geoplacerelation",
            trigger=pgtrigger.compiler.Trigger(
                name="upd_mod_4d608f6d",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    func="NEW.modified = NOW(); RETURN NEW;",
                    hash="2260c9555914397494a863dcd9ddd2dbae975994",
                    operation="UPDATE",
                    pgid="pgtrigger_upd_mod_4d608f6d_ab855",
                    table="geometries_geoplacerelation",
                    when="BEFORE",
                ),
            ),
        ),
        migrations.RunPython(seed_relations, unseed_relations),
    ]
