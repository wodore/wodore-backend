"""Merge duplicate Image rows sharing a source_ident, then make it unique.

``source_ident`` is the dedupe key for pinned provider images
("<provider>:<source_id>", server.apps.geometries.pinning) but had no
unique constraint — concurrent syncs (request-path write-through, django-q2
background refresh, ``geoimages_pin`` sweeps) could each see "no row" and
both create one. Every later sync then crashed in ``get_or_create``/``get``
with ``MultipleObjectsReturned`` ("get() returned more than one Image --
it returned 2!", Sentry 155850205, hut cedullo).

This merges existing duplicates: the oldest row per ident wins (matching
``Image.Meta.ordering`` and the runtime's canonical-row resolution in
``_get_or_create_pin``), hut/geoplace associations are re-pointed to the
keeper (links the keeper already has are dropped), the local file is
adopted if only a duplicate carries one, and finally the partial unique
constraint lands (empty/NULL idents stay unconstrained — uploads without
a source ident legitimately repeat).
"""

from django.conf import settings
from django.db import migrations, models
from django.db.models import Count


def merge_duplicate_pins(apps, schema_editor):
    Image = apps.get_model("images", "Image")
    HutImageAssociation = apps.get_model("huts", "HutImageAssociation")
    GeoPlaceImageAssociation = apps.get_model("geometries", "GeoPlaceImageAssociation")

    association_models = (
        (HutImageAssociation, "hut"),
        (GeoPlaceImageAssociation, "geo_place"),
    )

    dupe_idents = (
        Image.objects.filter(source_ident__gt="")
        .values("source_ident")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    for row in dupe_idents.iterator():
        ident = row["source_ident"]
        rows = list(Image.objects.filter(source_ident=ident).order_by("created", "id"))
        keeper, dupes = rows[0], rows[1:]
        keeper_dirty = False
        for dupe in dupes:
            # A duplicate may carry the pixels the keeper lacks (metadata-only
            # pin met a later import of the same file): adopt before deleting.
            if not keeper.image and dupe.image:
                keeper.image = dupe.image
                keeper_dirty = True
            for dupe_tag in dupe.tags.all():
                keeper.tags.add(dupe_tag)
            for model, place_field in association_models:
                for assoc in model.objects.filter(image=dupe):
                    place_id = getattr(assoc, f"{place_field}_id")
                    if model.objects.filter(
                        image_id=keeper.id, **{f"{place_field}_id": place_id}
                    ).exists():
                        assoc.delete()
                    else:
                        assoc.image = keeper
                        assoc.save(update_fields=["image"])
            dupe.delete()
        if keeper_dirty:
            keeper.save(update_fields=["image"])


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0032_alter_image_image"),
        ("licenses", "0011_alter_license_slug"),
        ("organizations", "0022_content_hash_logo_files"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        # Historical association models must exist in the migration state
        # when the merge re-points them.
        ("huts", "0067_alter_hutimageassociation_score"),
        ("geometries", "0050_alter_geoplaceimageassociation_score"),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_pins, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="image",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source_ident__gt", "")),
                fields=("source_ident",),
                name="images_image_source_ident_unique",
            ),
        ),
    ]
