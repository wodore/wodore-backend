from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from modeltrans.fields import TranslationField
from server.core.models import TimeStampedModel

if TYPE_CHECKING:
    pass


class GeoPlaceDetailBase(TimeStampedModel):
    """
    Abstract base class for all GeoPlace detail models.

    Provides automatic modification tracking that propagates to the parent GeoPlace.
    Child classes should define _trackable_fields to specify which fields to track.

    Example:
        class AmenityDetail(GeoPlaceDetailBase):
            _trackable_fields = ["operating_status", "opening_hours", "phones", "brand"]
    """

    class Meta:
        abstract = True

    # Child classes should override this
    _trackable_fields = []

    def save(self, *args, track_modifications=True, **kwargs):
        """Save the detail and track modifications to parent GeoPlace.

        Args:
            track_modifications: If True, track field changes and mark parent as modified.
                                Set to False during imports.
        """
        if track_modifications and self.pk:
            self._track_field_modifications()

        super().save(*args, **kwargs)

    def _track_field_modifications(self):
        """Track which fields were manually modified and update parent GeoPlace.

        This is called during save() when track_modifications=True (manual edits).
        During imports, track_modifications=False so fields remain unprotected.
        """
        if not self.pk:
            return  # New instance, nothing to track

        # Get original instance from database
        try:
            original = self.__class__.objects.get(pk=self.pk)
        except self.__class__.DoesNotExist:
            return

        # Get trackable fields from class configuration
        trackable_fields = self._get_trackable_fields()

        # Helper function to normalize values for comparison
        def normalize_value(value):
            """Treat None and empty string as equivalent."""
            if value is None or value == "":
                return ""
            return value

        # Track field changes
        modified_fields = []
        translation_fields = self._get_translation_fields()

        for field in trackable_fields:
            if field in translation_fields:
                # Handle translation fields with granular suffix tracking
                modified_fields.extend(
                    self._track_translation_field(original, field, normalize_value)
                )
            else:
                # Handle simple fields
                original_value = normalize_value(getattr(original, field, None))
                current_value = normalize_value(getattr(self, field, None))
                if original_value != current_value:
                    modified_fields.append(field)

        # Update parent GeoPlace if any fields were modified
        if modified_fields:
            place = self.geo_place
            place.is_modified = True

            # Add modified detail fields to parent's protected_fields
            current_protected = set(place.protected_fields)
            current_protected.update(modified_fields)
            place.protected_fields = list(current_protected)

            # Save parent without triggering its own modification tracking
            place.save(
                update_fields=["is_modified", "protected_fields"],
                track_modifications=False,
            )

    def _get_trackable_fields(self) -> list[str]:
        """Get list of fields to track for modifications.

        Returns fields defined in _trackable_fields class attribute.
        Child classes should override _trackable_fields.
        """
        return self._trackable_fields

    def _get_translation_fields(self) -> set[str]:
        """Automatically detect translation fields from TranslationField definition.

        Returns:
            Set of base field names that have translations (e.g., {'name', 'description'})
        """
        translation_fields = set()

        # Find all TranslationField instances in the model
        for field in self._meta.get_fields():
            if isinstance(field, TranslationField):
                # TranslationField has a 'fields' attribute listing translated fields
                if hasattr(field, "fields"):
                    translation_fields.update(field.fields)

        return translation_fields

    def _track_translation_field(
        self, original, field_name: str, normalize_value
    ) -> list[str]:
        """Track changes to a translation field with granular suffix protection.

        Strategy (matching GeoPlace):
        - Always use suffixes (field_de, field_en, etc.) - even for default language
        - Only protect the specific translation fields that were edited

        Args:
            original: Original instance from database
            field_name: Base field name (e.g., 'name', 'description')
            normalize_value: Function to normalize values for comparison

        Returns:
            List of modified field names (with suffixes like name_de, name_en)
        """
        modified = []

        # Check individual language translations (with suffixes)
        for lang_code in settings.LANGUAGE_CODES:
            if lang_code == settings.LANGUAGE_CODE:
                # For default language, use base field name
                suffixed_field = field_name
            else:
                # For other languages, use suffix
                suffixed_field = f"{field_name}_{lang_code}"

            original_value = normalize_value(getattr(original, suffixed_field, None))
            current_value = normalize_value(getattr(self, suffixed_field, None))

            if original_value != current_value:
                # Only protect this specific language (always use suffix format)
                modified.append(f"{field_name}_{lang_code}")

        return modified
