import django.contrib.gis.db.models.fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("huts", "0064_alter_hut_images_pinned_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hutsource",
            name="location",
            field=django.contrib.gis.db.models.fields.PointField(
                blank=True, default=None, null=True, verbose_name="Location"
            ),
        ),
    ]
