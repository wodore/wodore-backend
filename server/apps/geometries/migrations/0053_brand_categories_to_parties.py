"""Convert brand categories to parties and drop the ``brand`` FK.

OpenSpec change ``geoplace-parties`` (tasks 2.1 + 2.2): every
``AmenityDetail.brand`` Category reference becomes a ``Party`` (slug
and localized name preserved) plus a ``GeoPlaceParty`` association with
role ``role.brand``; then the FK is removed. ``root.brand`` category
rows stay in the database for rollback safety (cleanup in a later
change).

Rollback: reversing restores the (empty) ``brand`` column — the data
lives on in the Party rows and is re-derivable. The reverse of the
conversion is therefore a no-op.
"""

from django.db import IntegrityError, migrations


def convert_brand_to_party(apps, schema_editor):
    AmenityDetail = apps.get_model("geometries", "AmenityDetail")
    Party = apps.get_model("parties", "Party")
    GeoPlaceParty = apps.get_model("geometries", "GeoPlaceParty")
    Category = apps.get_model("categories", "Category")

    try:
        role_brand = Category.objects.get(identifier="role.brand")
    except Category.DoesNotExist:
        # Vocabulary not seeded — nothing to convert to.
        return

    for detail in AmenityDetail.objects.exclude(brand__isnull=True).select_related(
        "brand"
    ):
        category = detail.brand
        # Only the name_* translations carry over (Category also
        # translates description_*; Party translates name/note).
        i18n = {
            key: value
            for key, value in (category.i18n or {}).items()
            if key.startswith("name_")
        }
        # ``Party.slug`` is short-minted (max 15 — party-slug-minting);
        # OSM brand category slugs can exceed that (observed: 2129 of
        # 8914 on the dev clone). Copy the slug only when it fits —
        # otherwise mint a short one from the brand name (Party.save
        # does the minting when the slug is empty), keeping the brand
        # category slug on ``extra`` for re-derivation/rollback.
        if len(category.slug) <= 15:
            party, _created = Party.objects.get_or_create(
                slug=category.slug,
                defaults={
                    "name": category.name or category.slug.replace("_", " ").title(),
                    "i18n": i18n,
                },
            )
        else:
            # Historical models bypass ``Party.save()`` — mint the
            # short slug explicitly (same helper, same collision retry
            # semantics as the model).
            from server.core.utils import mint_short_slug

            base = category.name or category.slug.replace("_", " ").title()
            party = None
            for _attempt in range(3):
                try:
                    party = Party.objects.create(
                        slug=mint_short_slug(base, fallback="party"),
                        name=base,
                        i18n=i18n,
                        extra={"brand_slug": category.slug},
                    )
                    break
                except IntegrityError:
                    continue  # slug collision — mint again
            if party is None:
                raise RuntimeError(
                    f"could not mint a unique party slug for brand {category.slug!r}"
                )
        GeoPlaceParty.objects.get_or_create(
            geo_place_id=detail.geo_place_id, party=party, role=role_brand
        )


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0052_seed_role_vocabulary"),
        ("parties", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(convert_brand_to_party, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="amenitydetail",
            name="brand",
        ),
    ]
