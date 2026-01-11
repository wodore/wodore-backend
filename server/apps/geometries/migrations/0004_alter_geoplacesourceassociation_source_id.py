from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0003_update_country_constraint"),
    ]

    operations = [
        migrations.AlterField(
            model_name="geoplacesourceassociation",
            name="source_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Source id",
                max_length=100,
                null=True,
            ),
        ),
    ]
