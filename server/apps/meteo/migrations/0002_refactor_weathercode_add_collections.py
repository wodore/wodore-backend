# Generated migration for weather code refactoring
# Assumes fresh database with no existing data

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("meteo", "0001_initial"),
        ("organizations", "0020_organization_upd_mod_406b4872"),
        ("symbols", "0004_alter_symbol_style"),
    ]

    operations = [
        # Step 1: Remove old constraints and indexes from WeatherCode
        migrations.RemoveConstraint(
            model_name="weathercode",
            name="unique_source_slug",
        ),
        migrations.RemoveIndex(
            model_name="weathercode",
            name="meteo_weath_source__c6f7c7_idx",
        ),
        migrations.RemoveIndex(
            model_name="weathercode",
            name="meteo_weath_source__153857_idx",
        ),
        migrations.RemoveIndex(
            model_name="weathercode",
            name="meteo_weath_code_c969fa_idx",
        ),
        # Step 2: Remove old fields from WeatherCode
        migrations.RemoveField(
            model_name="weathercode",
            name="priority",
        ),
        migrations.RemoveField(
            model_name="weathercode",
            name="source_id",
        ),
        migrations.RemoveField(
            model_name="weathercode",
            name="source_organization",
        ),
        migrations.RemoveField(
            model_name="weathercode",
            name="symbol_day",
        ),
        migrations.RemoveField(
            model_name="weathercode",
            name="symbol_night",
        ),
        # Step 3: Make code and slug unique in WeatherCode
        migrations.AlterField(
            model_name="weathercode",
            name="code",
            field=models.PositiveSmallIntegerField(
                db_index=True,
                help_text="WMO weather code (e.g., 0 = clear sky, 61 = rain)",
                unique=True,
                verbose_name="Weather Code",
            ),
        ),
        migrations.AlterField(
            model_name="weathercode",
            name="slug",
            field=models.SlugField(
                max_length=100,
                unique=True,
                verbose_name="Slug",
            ),
        ),
        # Step 4: Update ordering for WeatherCode
        migrations.AlterModelOptions(
            name="weathercode",
            options={
                "verbose_name": "Weather Code",
                "verbose_name_plural": "Weather Codes",
                "ordering": ("code",),
            },
        ),
        # Step 5: Create WeatherCodeSymbolCollection model
        migrations.CreateModel(
            name="WeatherCodeSymbolCollection",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="modified",
                    ),
                ),
                (
                    "slug",
                    models.SlugField(
                        db_index=True,
                        help_text="Unique identifier for this symbol collection",
                        max_length=100,
                        unique=True,
                        verbose_name="Slug",
                    ),
                ),
                (
                    "source_org",
                    models.ForeignKey(
                        help_text="Organization providing this symbol collection",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="weather_symbol_collections",
                        to="organizations.organization",
                        verbose_name="Source Organization",
                    ),
                ),
            ],
            options={
                "verbose_name": "Weather Symbol Collection",
                "verbose_name_plural": "Weather Symbol Collections",
                "ordering": ("slug",),
            },
        ),
        # Step 6: Create WeatherCodeSymbol model
        migrations.CreateModel(
            name="WeatherCodeSymbol",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="modified",
                    ),
                ),
                (
                    "collection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="symbols",
                        to="meteo.weathercodesymbolcollection",
                        verbose_name="Symbol Collection",
                    ),
                ),
                (
                    "symbol_day",
                    models.ForeignKey(
                        blank=True,
                        help_text="Weather symbol for daytime",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="weather_code_symbols_day",
                        to="symbols.symbol",
                        verbose_name="Day Symbol",
                    ),
                ),
                (
                    "symbol_night",
                    models.ForeignKey(
                        blank=True,
                        help_text="Weather symbol for nighttime",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="weather_code_symbols_night",
                        to="symbols.symbol",
                        verbose_name="Night Symbol",
                    ),
                ),
                (
                    "weather_code",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="symbols",
                        to="meteo.weathercode",
                        verbose_name="Weather Code",
                    ),
                ),
            ],
            options={
                "verbose_name": "Weather Code Symbol",
                "verbose_name_plural": "Weather Code Symbols",
                "ordering": ("collection", "weather_code__code"),
            },
        ),
        # Step 7: Add unique constraint to WeatherCodeSymbol
        migrations.AddConstraint(
            model_name="weathercodesymbol",
            constraint=models.UniqueConstraint(
                fields=("weather_code", "collection"),
                name="unique_weathercode_collection",
            ),
        ),
    ]
