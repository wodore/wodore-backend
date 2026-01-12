# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("symbols", "0003_symbolgroup"),
        ("categories", "0009_migrate_category_symbols"),
    ]

    operations = [
        # Step 1: Remove old ImageField fields
        migrations.RemoveField(
            model_name="category",
            name="symbol_detailed",
        ),
        migrations.RemoveField(
            model_name="category",
            name="symbol_simple",
        ),
        migrations.RemoveField(
            model_name="category",
            name="symbol_mono",
        ),
        # Step 2: Rename new FK fields (remove the "2" suffix)
        migrations.RenameField(
            model_name="category",
            old_name="symbol_detailed2",
            new_name="symbol_detailed",
        ),
        migrations.RenameField(
            model_name="category",
            old_name="symbol_simple2",
            new_name="symbol_simple",
        ),
        migrations.RenameField(
            model_name="category",
            old_name="symbol_mono2",
            new_name="symbol_mono",
        ),
    ]
