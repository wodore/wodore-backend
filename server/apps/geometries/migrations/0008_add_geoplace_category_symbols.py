# Generated manually on 2026-01-13

from pathlib import Path
from django.db import migrations
from django.core.files import File


def add_geoplace_category_symbols(apps, schema_editor):
    """
    Add symbols to GeoPlace categories created in geometries.0002.

    Creates Symbol objects from SVG files in categories/assets and links them
    to GeoPlace categories using the same logic as categories.0009.
    """
    Category = apps.get_model("categories", "Category")
    Symbol = apps.get_model("symbols", "Symbol")
    License = apps.get_model("licenses", "License")

    # Get or create Flaticon Premium license
    license = License.objects.filter(slug="flaticon_premium").order_by().first()
    if not license:
        license = License(
            slug="flaticon_premium",
            name="Flaticon Premium",
            url="https://www.flaticon.com",
            link="https://www.flaticon.com/legal#nav-flaticon-agreement",
            attribution_required=False,
            no_commercial=False,
            is_active=True,
        )
        license.save()
        print("Created Flaticon Premium license")

    # Base path for category asset files
    base_path = Path(__file__).resolve().parent.parent / "categories" / "assets"

    def get_symbol_for_svg_file(svg_path, style):
        """
        Get or create a Symbol for a given SVG file path.
        """
        rel_path = svg_path.relative_to(base_path)

        # Generate slug from file path
        parts = list(rel_path.with_suffix('').parts)
        if len(parts) == 3 and parts[1] in ('detailed', 'simple', 'mono'):
            slug = parts[2]
        elif len(parts) == 2:
            slug = parts[0]
        else:
            slug_parts = [p for p in parts if p not in ('detailed', 'simple', 'mono')]
            slug = slug_parts[-1] if slug_parts else 'unknown'

        # Check for existing symbol
        existing = Symbol.objects.filter(slug=slug, style=style).first()
        if existing:
            return existing

        # Create new symbol
        new_symbol = Symbol(
            slug=slug,
            style=style,
            search_text=slug,
            license=license,
            is_active=True,
            review_status="approved",
        )

        # Save SVG file
        with open(svg_path, "rb") as f:
            new_symbol.svg_file.save(svg_path.name, File(f), save=True)

        print(f"    Created symbol: {slug} ({style})")
        return new_symbol

    def get_symbol_path(category, style):
        """
        Get the path to a symbol file for a category and style.

        Priority:
        1. assets/{category_slug}/{style}/{category_slug}.svg
        2. assets/{category_slug}/{style}/{parent_slug}.svg (parent fallback)
        3. assets/generic/{style}/generic.svg (ultimate fallback)
        """
        if category.parent:
            parent_slug = category.parent.slug
            child_slug = category.slug
        else:
            parent_slug = category.slug
            child_slug = None

        # Try child-specific symbol
        if child_slug:
            specific_path = base_path / parent_slug / style / f"{child_slug}.svg"
            if specific_path.exists():
                return specific_path

        # Fallback to parent symbol
        parent_path = base_path / parent_slug / style / f"{parent_slug}.svg"
        if parent_path.exists():
            return parent_path

        # Fallback to generic
        generic_path = base_path / "generic" / style / "generic.svg"
        if generic_path.exists():
            return generic_path

        return None

    # Process GeoPlace parent categories
    geo_place_parents = [
        "terrain", "hydrographic", "populated_place",
        "administrative", "transport", "spot"
    ]

    linked_count = 0
    skipped_count = 0

    for category_slug in geo_place_parents:
        try:
            category = Category.objects.get(slug=category_slug, parent=None)

            # Skip if already has all symbols
            if category.symbol_detailed and category.symbol_simple and category.symbol_mono:
                print(f"  ⊘ Skipped {category_slug} (already has symbols)")
                skipped_count += 1
                continue

            # Get symbol paths and create/link symbols
            needs_save = False

            for style in ["detailed", "simple", "mono"]:
                svg_path = get_symbol_path(category, style)
                if svg_path:
                    symbol = get_symbol_for_svg_file(svg_path, style)

                    # Link to category
                    if style == "detailed":
                        category.symbol_detailed = symbol
                    elif style == "simple":
                        category.symbol_simple = symbol
                    elif style == "mono":
                        category.symbol_mono = symbol

                    needs_save = True

            if needs_save:
                category.save()
                linked_count += 1
                print(f"  ✓ Linked symbols to {category_slug}")

        except Category.DoesNotExist:
            print(f"  ⚠ Warning: Category not found: {category_slug}")

    print(f"\nMigration summary:")
    print(f"  Categories linked: {linked_count}")
    print(f"  Categories skipped: {skipped_count}")


def reverse_migration(apps, schema_editor):
    """
    Reverse migration - remove symbol links from GeoPlace categories.
    """
    Category = apps.get_model("categories", "Category")

    geo_place_slugs = [
        "terrain", "hydrographic", "populated_place",
        "administrative", "transport", "spot"
    ]

    count = Category.objects.filter(
        slug__in=geo_place_slugs,
        parent=None
    ).update(
        symbol_detailed=None,
        symbol_simple=None,
        symbol_mono=None
    )

    print(f"✓ Removed symbols from {count} GeoPlace categories")


class Migration(migrations.Migration):

    dependencies = [
        ("geometries", "0007_remove_geoplace_geometries_geoplace_country_valid_and_more"),
        ("symbols", "0004_alter_symbol_style"),
        ("licenses", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            add_geoplace_category_symbols,
            reverse_migration,
        ),
    ]
