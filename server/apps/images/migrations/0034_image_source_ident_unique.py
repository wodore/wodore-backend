"""Partial unique constraint on Image.source_ident.

Lands in its own migration, deliberately separate from the dedupe data
migration ``0033_merge_duplicate_pins_unique_source_ident``: migrations are
atomic (one transaction), and Postgres refuses ``CREATE UNIQUE INDEX``
while the transaction still has pending deferred trigger events — Django
creates foreign keys as ``DEFERRABLE INITIALLY DEFERRED``, so 0033's DML
queues FK-check trigger events that only fire at COMMIT. Combining both
operations made the staging migrate job die with ``cannot CREATE INDEX
"images_image" because it has pending trigger events`` (Sentry
BACKEND-DJANGO-8, release d3bdc2bc). Never merge this constraint back into
a migration that also writes rows; see Django ticket #31106.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0033_merge_duplicate_pins_unique_source_ident"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="image",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source_ident__gt", "")),
                fields=("source_ident",),
                name="images_image_source_ident_unique",
            ),
        ),
    ]
