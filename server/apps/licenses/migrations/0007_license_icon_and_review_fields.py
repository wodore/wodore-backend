# Generated migration

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("licenses", "0006_license_upd_mod_26a7a6c1"),
        ("categories", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="license",
            name="category",
            field=models.ForeignKey(
                blank=True,
                help_text="Category for license symbols (references detailed/simple/mono symbols)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="licenses",
                to="categories.category",
                verbose_name="Category",
            ),
        ),
        migrations.AddField(
            model_name="license",
            name="review_status",
            field=models.CharField(
                max_length=20,
                default="done",
                help_text="Review status: 'new' for auto-added, 'done' for reviewed",
                choices=[("new", "New"), ("done", "Done"), ("rejected", "Rejected")],
            ),
        ),
        migrations.AddField(
            model_name="license",
            name="review_comment",
            field=models.TextField(
                blank=True,
                null=True,
                help_text="Review comments or notes",
            ),
        ),
    ]
