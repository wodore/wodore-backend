"""Reband image association scores into the API contract's 0–100.

The curated-upload band used to start at ``UPLOAD_DEFAULT_SCORE = 1000``
(imports stacking upward), while the image endpoints validate
``properties.score`` against 0–100 — any hut with an imported image 500'd as
soon as its licenses became servable (staging 2026-10). Bands move to:
uploads 90–99 (newest import first), provider pins ≤ 89 (clamped at pin time).

- score >= 1000  → reband into 90..99 per place, newest import first (>10
  imports share the top slot; ordering falls back to id).
- 90 <= score < 1000 → clamp to 89 (strong pins 90–100 or manual scores that
  sat in the old gap are treated as pins; deliberate re-curation can re-raise
  them inside the upload band).
- score <= 89 → untouched.
"""

from django.db import migrations


def remap_scores(apps, schema_editor):
    HutImageAssociation = apps.get_model("huts", "HutImageAssociation")
    GeoPlaceImageAssociation = apps.get_model("geometries", "GeoPlaceImageAssociation")

    for model, place_field in (
        (HutImageAssociation, "hut_id"),
        (GeoPlaceImageAssociation, "geo_place_id"),
    ):
        model.objects.filter(score__gte=90, score__lt=1000).update(score=89)

        place_ids = (
            model.objects.filter(score__gte=1000)
            .values_list(place_field, flat=True)
            .distinct()
        )
        for place_id in place_ids.iterator():
            uploads = model.objects.filter(
                **{place_field: place_id, "score__gte": 1000}
            ).order_by("-score")
            for index, assoc in enumerate(uploads):
                new_score = max(90, 99 - index)
                if assoc.score != new_score:
                    assoc.score = new_score
                    assoc.save(update_fields=["score"])


class Migration(migrations.Migration):
    dependencies = [
        ("huts", "0065_hutsource_location_nullable"),
        ("geometries", "0049_alter_objectvisitday_unique_together_and_more"),
    ]

    operations = [
        migrations.RunPython(remap_scores, migrations.RunPython.noop),
    ]
