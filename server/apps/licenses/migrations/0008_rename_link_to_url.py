# Generated migration to rename link to url

from django.db import migrations


def rename_link_to_url_in_i18n(apps, schema_editor):
    """Rename link_LANG to url_LANG in i18n JSON field."""
    License = apps.get_model("licenses", "License")

    # Use order_by() to avoid default ordering that references name_i18n
    for license in License.objects.all().order_by("pk"):
        if license.i18n:
            updated = False
            # Rename all link_LANG keys to url_LANG
            for key in list(license.i18n.keys()):
                if key.startswith("link_"):
                    lang_code = key.replace("link_", "")
                    license.i18n[f"url_{lang_code}"] = license.i18n.pop(key)
                    updated = True
            if updated:
                license.save(update_fields=["i18n"])


def reverse_url_to_link_in_i18n(apps, schema_editor):
    """Reverse: rename url_LANG to link_LANG in i18n JSON field."""
    License = apps.get_model("licenses", "License")

    # Use order_by() to avoid default ordering that references name_i18n
    for license in License.objects.all().order_by("pk"):
        if license.i18n:
            updated = False
            # Rename all url_LANG keys back to link_LANG
            for key in list(license.i18n.keys()):
                if key.startswith("url_"):
                    lang_code = key.replace("url_", "")
                    license.i18n[f"link_{lang_code}"] = license.i18n.pop(key)
                    updated = True
            if updated:
                license.save(update_fields=["i18n"])


class Migration(migrations.Migration):
    dependencies = [
        ("licenses", "0007_license_icon_and_review_fields"),
    ]

    operations = [
        # Run data migration BEFORE renaming the field
        migrations.RunPython(rename_link_to_url_in_i18n, reverse_url_to_link_in_i18n),
        # Then rename the database field
        migrations.RenameField(
            model_name="license",
            old_name="link",
            new_name="url",
        ),
    ]
