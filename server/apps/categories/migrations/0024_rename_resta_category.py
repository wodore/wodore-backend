from django.db import migrations


def rename_resta_to_restaurant(apps, schema_editor):
    Category = apps.get_model("categories", "Category")
    Symbol = apps.get_model("symbols", "Symbol")
    # The accommodation icon pack renamed its icon resta -> restaurant; align
    # the category slug. The linked resta symbols are retired (is_active=False)
    # so the stale slug stops being served; category_sync_assets relinks the
    # category to the existing restaurant symbols (slug+style reuse) and
    # re-uploads the new SVGs.
    Category.objects.filter(slug="resta").update(slug="restaurant")
    Symbol.objects.filter(slug="resta").update(is_active=False)


def rename_restaurant_to_resta(apps, schema_editor):
    Category = apps.get_model("categories", "Category")
    Symbol = apps.get_model("symbols", "Symbol")
    Category.objects.filter(
        slug="restaurant", parent__slug="accommodation"
    ).update(slug="resta")
    Symbol.objects.filter(slug="resta").update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0023_category_is_protected"),
    ]

    operations = [
        migrations.RunPython(rename_resta_to_restaurant,
                             rename_restaurant_to_resta),
    ]
