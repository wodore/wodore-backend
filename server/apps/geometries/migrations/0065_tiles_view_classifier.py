"""Recreate the tiles view with the classifier column.

The sole view recreation point for this change (deferred from 0059 —
the model SQL references tables created by 0061+; recreating at 0059
would fail on fresh databases). Task 3.2 + advisor P0 fix.

``geoplace-category-tree``: the SQL is now EMBEDDED (frozen at merge
time), not live-imported from the model — the model column renamed to
``kind_slug`` in 0066, and a live import would render the new SQL
against the still-``detail_type`` database on fresh runs. 0066 drops
and recreates the view with the ``kind_slug`` shape.
"""

from typing import Any

from django.db import migrations

#: View SQL as of this migration (detail_type era) — rendered from
#: GeoPlacesForTilesView.ViewMeta.query() at authoring time.
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
              -- Each category has: slug, identifier, order, color, parent_slug,
              -- parent_name, classifier (mode.* identifier), extra.
              -- Capacity is NOT joined here — the model SQL must not
              -- reference tables created by later migrations (fresh-DB
              -- view creation in 0027+ would fail). Capacity reaches
              -- tile consumers through the martin tile function's own
              -- query layer (task 4.5 documented in the work doc).
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
                      'classifier', clf.identifier,
                      'extra', gpc.extra
                    )
                    ORDER BY cat."order"
                  )
                  FROM geometries_geoplace_category gpc
                  LEFT JOIN categories_category cat ON gpc.category_id = cat.id
                  LEFT JOIN categories_category parent ON cat.parent_id = parent.id
                  LEFT JOIN categories_category clf ON gpc.classifier_id = clf.id
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


def recreate_view(_apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS geoplaces_for_tiles CASCADE")
        cursor.execute(f"CREATE VIEW geoplaces_for_tiles AS {VIEW_SQL}")


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0064_replace_parent_with_relations"),
    ]

    operations = [
        migrations.RunPython(
            code=recreate_view,
            reverse_code=recreate_view,
        ),
    ]
