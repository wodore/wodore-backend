from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("external_links", "0006_populate_identifiers"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE external_links_externallink ALTER COLUMN identifier SET NOT NULL",
            reverse_sql="ALTER TABLE external_links_externallink ALTER COLUMN identifier DROP NOT NULL"
        ),
    ]
