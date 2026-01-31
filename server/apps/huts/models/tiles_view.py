"""
PostgreSQL view for Martin vector tiles.

This view provides optimized data structure for serving huts as vector tiles.
It includes all necessary fields with JOINs pre-computed for performance.
"""

from django.conf import settings
from django.contrib.gis.db import models
from psqlextra.models import PostgresViewModel


class HutsForTilesView(PostgresViewModel):
    """
    PostgreSQL view for Martin vector tile server.

    Provides huts data with:
    - Multilingual names (de, en, fr, it) with fallbacks via modeltrans
    - Hut type slugs and order (not IDs)
    - Availability status
    - Organization sources
    - Owner information

    Only includes public and active huts.

    Note: Using SQL instead of QuerySet because PostgresViewModel compiles
    the query at import time, before Django apps are ready. This means we
    cannot use ORM features that require model access.
    """

    # Core fields
    slug = models.CharField(max_length=50, primary_key=True)
    location = models.PointField(srid=4326)

    # Elevation and capacity
    elevation = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    capacity_standard = models.PositiveSmallIntegerField(null=True, blank=True)
    capacity_reduced = models.PositiveSmallIntegerField(null=True, blank=True)

    # Default language name with fallbacks (based on MODELTRANS_FALLBACK)
    name = models.CharField(max_length=100)

    # Multilingual names (de, en, fr, it)
    # These will be populated based on LANGUAGES setting with fallbacks
    name_de = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)
    name_fr = models.CharField(max_length=100)
    name_it = models.CharField(max_length=100)

    # Hut type (standard state - formerly "open")
    type_standard_slug = models.CharField(max_length=50, null=True, blank=True)
    type_standard_order = models.PositiveSmallIntegerField(null=True, blank=True)
    type_standard_identifier = models.CharField(max_length=102, null=True, blank=True)

    # Hut type (reduced state - formerly "closed", for winter bivouacs)
    type_reduced_slug = models.CharField(max_length=50, null=True, blank=True)
    type_reduced_order = models.PositiveSmallIntegerField(null=True, blank=True)
    type_reduced_identifier = models.CharField(max_length=102, null=True, blank=True)

    # Availability
    has_availability = models.BooleanField(default=False)

    # Owner
    owner_slug = models.CharField(max_length=50, null=True, blank=True)
    owner_name = models.CharField(max_length=100, null=True, blank=True)

    # Sources (array of objects with slug and source_id)
    sources = models.JSONField(default=list)

    class Meta:
        managed = False
        db_table = "huts_for_tiles"

    class ViewMeta:
        """
        ViewMeta configuration for django-postgres-extra.

        The 'query' attribute can be SQL string or (SQL, params) tuple.
        Using SQL allows the view to be created at migration time.
        """

        @staticmethod
        def query():
            """
            Generate SQL for creating the view.

            Uses COALESCE for multilingual fallbacks based on MODELTRANS_FALLBACK setting.
            Matches the same pattern used in the API endpoints for consistency.

            Returns (SQL, params) tuple.
            """
            # Get fallback configuration
            fallback_config = getattr(settings, "MODELTRANS_FALLBACK", {})
            language_code = settings.LANGUAGE_CODE  # 'de'
            languages = getattr(settings, "LANGUAGE_CODES", ["de", "en", "fr", "it"])

            # Build COALESCE statements for each language with fallbacks
            name_selects = []
            for lang in languages:
                # Get fallback chain for this language
                fallbacks = fallback_config.get(lang, [language_code])
                fallback_chain = [lang] + [fb for fb in fallbacks if fb != lang]

                # Build COALESCE expression
                coalesce_parts = []
                for fallback_lang in fallback_chain:
                    if fallback_lang == language_code:
                        # Default language is in 'name' field
                        coalesce_parts.append("h.name")
                    else:
                        # Other languages in i18n JSONB field
                        coalesce_parts.append(f"h.i18n->>'name_{fallback_lang}'")

                # Add final fallback to name if not already included
                if "h.name" not in coalesce_parts:
                    coalesce_parts.append("h.name")

                coalesce_expr = f"COALESCE({', '.join(coalesce_parts)}) as name_{lang}"
                name_selects.append(coalesce_expr)

            name_columns = ",\n      ".join(name_selects)

            # Build the name field for default language (must duplicate the expression, can't use alias)
            # Get the COALESCE expression for the default language
            default_lang_coalesce = None
            for i, lang in enumerate(languages):
                if lang == language_code:
                    # This is the expression we need to duplicate
                    default_fallbacks = fallback_config.get(lang, [language_code])
                    fallback_chain = [lang] + [
                        fb for fb in default_fallbacks if fb != lang
                    ]

                    coalesce_parts = []
                    for fallback_lang in fallback_chain:
                        if fallback_lang == language_code:
                            coalesce_parts.append("h.name")
                        else:
                            coalesce_parts.append(f"h.i18n->>'name_{fallback_lang}'")

                    if "h.name" not in coalesce_parts:
                        coalesce_parts.append("h.name")

                    default_lang_coalesce = f"COALESCE({', '.join(coalesce_parts)})"
                    break

            sql = f"""
            SELECT
              h.slug,
              h.location,
              h.elevation,
              h.capacity_open as capacity_standard,
              h.capacity_closed as capacity_reduced,

              -- Default language name with fallbacks (based on MODELTRANS_FALLBACK)
              {default_lang_coalesce} as name,

              -- Multilingual names with fallbacks (based on MODELTRANS_FALLBACK)
              {name_columns},

              -- Hut type (standard state - formerly "open")
              cat_open.slug as type_standard_slug,
              cat_open."order" as type_standard_order,
              cat_open.identifier as type_standard_identifier,

              -- Hut type (reduced state - formerly "closed")
              cat_closed.slug as type_reduced_slug,
              cat_closed."order" as type_reduced_order,
              cat_closed.identifier as type_reduced_identifier,

              -- Availability status
              (h.availability_source_ref_id IS NOT NULL) as has_availability,

              -- Owner information
              owner.slug as owner_slug,
              owner.name as owner_name,

              -- Organization sources (slug and source_id)
              -- Matches the pattern used in API endpoints
              -- Cast to jsonb to ensure Django JSONField compatibility
              COALESCE(
                (
                  SELECT jsonb_agg(
                    jsonb_build_object(
                      'slug', o.slug,
                      'source_id', hoa.source_id
                    )
                  )
                  FROM huts_hutorganizationassociation hoa
                  LEFT JOIN organizations_organization o ON hoa.organization_id = o.id
                  WHERE hoa.hut_id = h.id AND o.slug IS NOT NULL
                ),
                '[]'::jsonb
              ) as sources

            FROM huts_hut h
            LEFT JOIN categories_category cat_open ON h.hut_type_open_id = cat_open.id
            LEFT JOIN categories_category cat_closed ON h.hut_type_closed_id = cat_closed.id
            LEFT JOIN owners_owner owner ON h.hut_owner_id = owner.id
            WHERE h.is_public = true AND h.is_active = true
            """

            # Return tuple of (SQL, params) - no params needed for this query
            return (sql.strip(), [])
