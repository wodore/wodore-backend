"""CategoryKindContract model + GeoPlace.detail_type → kind_slug.

OpenSpec ``geoplace-category-tree`` (tasks 1.1 + 1.3):

* ``CategoryKindContract`` — the DB kind contract on a contract-group
  category (seeded by 0067), admin-editable.
* ``GeoPlace.detail_type`` renames to ``kind_slug`` — the super-root
  identifier (``map.amenity`` / ``map.admin`` / ``map.natural``),
  free-form (the tree validates; the enum check constraint drops).
  Stored values convert: amenity/transport → map.amenity (transport
  sits under the amenity super-root), admin → map.admin, natural →
  map.natural, none stays none.
* The tiles view is dropped and recreated from the current model SQL
  (``kind_slug`` shape) — live import is correct at this point in the
  chain.
"""

from typing import Any

import pgtrigger.compiler
import pgtrigger.migrations

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

import server.core.models


def convert_kind_slugs(apps: Any, schema_editor: Any) -> None:
    GeoPlace = apps.get_model("geometries", "GeoPlace")
    # The per-row pgtrigger overhead on the mass UPDATE exceeds the
    # connection's 15 s statement timeout (common.py) — lift it for
    # this transaction (SET LOCAL binds to the migration's atomic).
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = '120s'")
    mapping = {
        "amenity": "map.amenity",
        "transport": "map.amenity",
        "admin": "map.admin",
        "natural": "map.natural",
    }
    for old, new in mapping.items():
        GeoPlace.objects.filter(kind_slug=old).update(kind_slug=new)


def reverse_kind_slugs(apps: Any, _schema_editor: Any) -> None:
    GeoPlace = apps.get_model("geometries", "GeoPlace")
    mapping = {
        "map.amenity": "amenity",  # transport rows merge into amenity
        "map.admin": "admin",
        "map.natural": "natural",
    }
    for new, old in mapping.items():
        GeoPlace.objects.filter(kind_slug=new).update(kind_slug=old)


def drop_tiles_view(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")


def recreate_tiles_view(_apps: Any, schema_editor: Any) -> None:
    from server.apps.geometries.models.tiles_view import GeoPlacesForTilesView

    sql, params = GeoPlacesForTilesView.ViewMeta.query()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")
        cursor.execute(f"CREATE VIEW geoplaces_for_tiles AS {sql}", params)


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0023_category_is_protected"),
        ("external_links", "0011_uri_kind_column"),
        ("geometries", "0065_tiles_view_classifier"),
        ("images", "0034_image_source_ident_unique"),
        ("organizations", "0022_content_hash_logo_files"),
    ]

    operations = [
        # The view depends on the renamed column — drop it first (PG
        # forbids ALTER TYPE under a view), recreate at the end.
        migrations.RunPython(drop_tiles_view, migrations.RunPython.noop),
        migrations.CreateModel(
            name="CategoryKindContract",
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
                    "has_operations",
                    models.BooleanField(
                        default=False,
                        help_text="Places under this group may carry operation rows",
                        verbose_name="Has operations",
                    ),
                ),
                (
                    "has_seasonality",
                    models.BooleanField(
                        default=False,
                        help_text="Places under this group may carry seasonality rows",
                        verbose_name="Has seasonality",
                    ),
                ),
            ],
            options={
                "verbose_name": "Category Kind Contract",
                "verbose_name_plural": "Category Kind Contracts",
                "ordering": ["category__slug"],
            },
        ),
        migrations.AddField(
            model_name="categorykindcontract",
            name="category",
            field=models.OneToOneField(
                help_text="The contract-group category (e.g. accommodation for accommodation.hut) this contract applies to",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="kind_contract",
                to="categories.category",
                verbose_name="Contract group",
            ),
        ),
        migrations.AddField(
            model_name="categorykindcontract",
            name="allowed_classifiers",
            field=models.ManyToManyField(
                blank=True,
                help_text="Classifier vocabulary roots (mode, role, …) permitted on associations under this group",
                limit_choices_to=models.Q(
                    ("parent__isnull", True), models.Q(("slug", "map"), _negated=True)
                ),
                related_name="kind_contracts",
                to="categories.category",
                verbose_name="Allowed classifiers",
            ),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="categorykindcontract",
            trigger=pgtrigger.compiler.Trigger(
                name="upd_mod_42f1772c",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    func="NEW.modified = NOW(); RETURN NEW;",
                    hash="1ccbe99d7b7f1371782e313ee2fb6ccf2851791e",
                    operation="UPDATE",
                    pgid="pgtrigger_upd_mod_42f1772c_b0d9d",
                    table="geometries_categorykindcontract",
                    when="BEFORE",
                ),
            ),
        ),
        migrations.RemoveConstraint(
            model_name="geoplace",
            name="geometries_geoplace_detail_type_valid",
        ),
        migrations.RemoveIndex(
            model_name="geoplace",
            name="geometries__detail__6f11a2_idx",
        ),
        migrations.RenameField(
            model_name="geoplace",
            old_name="detail_type",
            new_name="kind_slug",
        ),
        migrations.AlterField(
            model_name="geoplace",
            name="kind_slug",
            field=models.CharField(
                db_index=True,
                default="none",
                help_text="Super-root identifier of the place's kind (derived)",
                max_length=100,
                verbose_name="Kind Slug",
            ),
        ),
        migrations.AddIndex(
            model_name="geoplace",
            index=models.Index(
                fields=["kind_slug"], name="geometries__kind_sl_c6f402_idx"
            ),
        ),
        migrations.RunPython(convert_kind_slugs, reverse_kind_slugs),
        # Reverse DROPS the view (not recreate): recreating would
        # re-attach kind_slug SQL, then RenameField's reversal renames
        # the column back to detail_type — a view over a missing
        # column. 0065's reverse recreates the detail_type-era view.
        migrations.RunPython(recreate_tiles_view, drop_tiles_view),
    ]
