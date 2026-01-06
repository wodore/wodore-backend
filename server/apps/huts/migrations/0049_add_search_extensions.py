# Generated manually for search functionality
from django.contrib.postgres.operations import TrigramExtension, UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):
    """
    Adds PostgreSQL extensions required for fuzzy/similarity search:
    - pg_trgm: Trigram similarity matching for typo tolerance
    - unaccent: Accent-insensitive text search
    """

    dependencies = [
        ("huts", "0048_rename_booking_ref_to_availability_source_ref"),
    ]

    operations = [
        TrigramExtension(),
        UnaccentExtension(),
    ]
