from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("symbols", "0005_add_new_symbol_styles"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE symbols_symbol ALTER COLUMN style TYPE VARCHAR(20);",
            "ALTER TABLE symbols_symbol ALTER COLUMN style TYPE VARCHAR(10);"
        ),
    ]
