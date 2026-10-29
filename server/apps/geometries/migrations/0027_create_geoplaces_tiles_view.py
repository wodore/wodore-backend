# Generated manually to create GeoPlacesForTilesView

from typing import Any

# ``geoplace-category-tree``: the SQL is now EMBEDDED (frozen at
# authoring time), not live-imported from the model — the model
# column renamed to ``kind_slug`` in 0066, and a live import would
# render the new SQL against the still-``detail_type`` database on
# fresh runs. 0030/0059/0065/0066 recreate the view; each embeds the
# SQL of its own era.
from django.db import migrations

#: View SQL as of this migration (detail_type era, no classifier) —
#: rendered from GeoPlacesForTilesView.ViewMeta.query() at authoring
#: time (identical era as 0030).
VIEW_SQL = """SELECT DISTINCT ON (gp.id)
              gp.slug,
              gp.location,
              gp.elevation,
              gp.country_code,
              gp.importance,
              gp.detail_type,
              gp.extra,

              -- Default language name with fallbacks (based on MODELTRANS_FALLBACK)
              COALESCE(gp.name, gp.i18n->>'name_en', gp.i18n->>'name_fr') as name,

              -- Multilingual names with fallbacks (based on MODELTRANS_FALLBACK)
              COALESCE(gp.name, gp.i18n->>'name_en', gp.i18n->>'name_fr') as name_de,
      COALESCE(gp.i18n->>'name_en', gp.name, gp.i18n->>'name_fr') as name_en,
      COALESCE(gp.i18n->>'name_fr', gp.i18n->>'name_it', gp.name, gp.i18n->>'name_en') as name_fr,
      COALESCE(gp.i18n->>'name_it', gp.i18n->>'name_fr', gp.name, gp.i18n->>'name_en') as name_it,

              -- Categories (JSON array with all categories for this place)
              -- Each category has: slug, identifier, order, color, parent_slug, parent_name, extra
              COALESCE(
                (
                  SELECT jsonb_agg(
                    jsonb_build_object(
                      'slug', cat.slug,
                      'identifier', cat.identifier,
                      'order', cat."order",
                      'color', cat.color,
                      'parent_slug', parent.slug,
                      'parent_name', parent.name,
                      'extra', gpc.extra
                    )
                    ORDER BY cat."order"
                  )
                  FROM geometries_geoplace_category gpc
                  LEFT JOIN categories_category cat ON gpc.category_id = cat.id
                  LEFT JOIN categories_category parent ON cat.parent_id = parent.id
                  WHERE gpc.geo_place_id = gp.id AND cat.id IS NOT NULL
                ),
                '[]'::jsonb
              ) as categories,

              -- Organization sources (slug and source_id)
              -- Matches the pattern used in HutsForTilesView
              COALESCE(
                (
                  SELECT jsonb_agg(
                    jsonb_build_object(
                      'slug', o.slug,
                      'source_id', gsa.source_id
                    )
                  )
                  FROM geometries_geoplacesourceassociation gsa
                  LEFT JOIN organizations_organization o ON gsa.organization_id = o.id
                  WHERE gsa.geo_place_id = gp.id AND o.slug IS NOT NULL
                ),
                '[]'::jsonb
              ) as sources

            FROM geometries_geoplace gp
            WHERE gp.is_public = true AND gp.is_active = true"""


def create_view_from_model(_apps: Any, schema_editor: Any) -> None:
    """Create the view (era-frozen SQL — see module docstring)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")
        cursor.execute(f"CREATE VIEW geoplaces_for_tiles AS {VIEW_SQL}")


def drop_view(_apps: Any, schema_editor: Any) -> None:
    """Drop the view."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0026_alter_geoplace_categories_and_more"),
    ]

    operations = [
        migrations.RunPython(
            code=create_view_from_model,
            reverse_code=drop_view,
        ),
    ]
