from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import F, FloatField, Q, Value
from django.db.models.functions import Coalesce, Greatest
from modeltrans.manager import MultilingualManager

from server.core.managers import BaseManager


class HutManager(MultilingualManager, BaseManager):
    """Manager for Hut model with search capabilities."""

    def search(
        self,
        query: str,
        language: str | None = None,
        threshold: float = 0.1,
        is_active: bool = True,
        is_public: bool = True,
    ):
        """
        Hybrid search using PostgreSQL full-text search and trigram similarity.

        Combines:
        - Full-text search: Natural language search with stemming and ranking
        - Trigram similarity: Fuzzy matching for typos and partial matches

        Args:
            query: Search query string
            language: Primary language for search. If None, uses settings.LANGUAGE_CODE
            threshold: Minimum similarity score (0-1). Default: 0.1
            is_active: Filter by active status. Default: True
            is_public: Filter by public status. Default: True

        Returns:
            QuerySet ordered by relevance score (highest first)

        Example:
            >>> Hut.objects.search("Rotondo")
            >>> Hut.objects.search("Rotnd", threshold=0.3)  # Fuzzy match for typo
        """
        # Use configured language settings
        if language is None:
            language = settings.LANGUAGE_CODE

        available_languages = settings.LANGUAGE_CODES

        # Map language codes to PostgreSQL text search configurations
        lang_config_map = {
            "de": "german",
            "en": "english",
            "fr": "french",
            "it": "italian",
        }
        primary_config = lang_config_map.get(language, "simple")

        # Build search vectors
        # The 'name' field contains the primary language (German by default)
        # The 'i18n' JSONB field contains other translations
        search_vectors = [SearchVector("name", weight="A", config=primary_config)]

        # Add other language translations from i18n JSONB
        for lang_code in available_languages:
            if lang_code == settings.LANGUAGE_CODE:
                continue  # Already included as base 'name' field
            lang_config = lang_config_map.get(lang_code, "simple")
            search_vectors.append(
                SearchVector(f"i18n__name_{lang_code}", weight="B", config=lang_config)
            )

        # Combine all search vectors
        combined_search_vector = search_vectors[0]
        for sv in search_vectors[1:]:
            combined_search_vector = combined_search_vector + sv

        # Create search query
        search_query = SearchQuery(query, config=primary_config)

        # Calculate trigram similarity
        # We'll create an expression that uses unaccent() for accent-insensitive matching
        from django.db.models.expressions import RawSQL

        # For trigram with unaccent, we need to use RawSQL since TrigramSimilarity
        # doesn't support complex expressions like Unaccent(field)
        # Format: similarity(unaccent(field), unaccent(query))

        similarity_annotations = {
            # Base name field with unaccent for accent-insensitive matching
            # Use fully qualified table name to avoid ambiguity when joining
            "trigram_sim_primary": RawSQL(
                'similarity(unaccent("huts_hut"."name"), unaccent(%s))', (query,)
            )
        }

        # Add trigram similarity for other languages in i18n
        for lang_code in available_languages:
            if lang_code == settings.LANGUAGE_CODE:
                continue  # Already included as base 'name'
            # JSONB field access with unaccent - use fully qualified table name
            similarity_annotations[f"trigram_sim_{lang_code}"] = RawSQL(
                'similarity(unaccent(COALESCE("huts_hut"."i18n"->>%s, \'\')), unaccent(%s))',
                (f"name_{lang_code}", query),
            )

        # Start with base queryset
        qs = self.get_queryset()

        # Apply filters
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        if is_public is not None:
            qs = qs.filter(is_public=is_public)

        # Build annotation dict dynamically
        annotations = {
            "search_rank": Coalesce(
                SearchRank(combined_search_vector, search_query),
                Value(0.0),
                output_field=FloatField(),
            ),
        }

        # Add the trigram similarity annotations
        annotations.update(similarity_annotations)

        # Annotate with search rank and individual similarity scores
        qs = qs.annotate(**annotations)

        # Calculate maximum similarity across all language fields
        similarity_field_names = list(similarity_annotations.keys())
        max_sim_fields = [F(name) for name in similarity_field_names]
        qs = qs.annotate(
            trigram_sim=Greatest(*max_sim_fields, output_field=FloatField()),
            # Combined score: equal weight for simplicity
            combined_score=(F("search_rank") + F("trigram_sim")) / 2.0,
        )

        # Filter by minimum score
        qs = qs.filter(Q(search_rank__gt=threshold) | Q(trigram_sim__gt=threshold))

        # Order by combined score (highest first)
        return qs.order_by("-combined_score")


# HutManager = _HutManager.from_queryset(BaseQuerySet)
