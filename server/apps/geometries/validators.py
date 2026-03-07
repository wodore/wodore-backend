from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _


class WebsitesValidator:
    """
    Validator for JSONField containing list of website objects.

    Expected format:
    [
        {"url": "https://example.com", "label": "Official"},
        {"url": "https://booking.example.com", "label": "Booking"}
    ]

    Each item must have:
    - url (required): Valid URL string
    - label (optional): String describing the website
    """

    def __init__(self):
        self.url_validator = URLValidator()

    def __call__(self, value: list) -> None:
        """
        Validate the websites JSON structure.

        Args:
            value: List of website dictionaries

        Raises:
            ValidationError: If structure is invalid
        """
        if not isinstance(value, list):
            raise ValidationError(
                _("Websites must be a list of objects"),
                code="websites_not_list",
            )

        for idx, website in enumerate(value):
            if not isinstance(website, dict):
                raise ValidationError(
                    _("Website at index %(index)s must be an object"),
                    code="website_not_dict",
                    params={"index": idx},
                )

            # Validate required 'url' field
            if "url" not in website:
                raise ValidationError(
                    _("Website at index %(index)s missing required 'url' field"),
                    code="website_missing_url",
                    params={"index": idx},
                )

            url = website["url"]
            if not isinstance(url, str):
                raise ValidationError(
                    _("Website URL at index %(index)s must be a string"),
                    code="website_url_not_string",
                    params={"index": idx},
                )

            # Validate URL format
            try:
                self.url_validator(url)
            except ValidationError as e:
                raise ValidationError(
                    _("Website URL at index %(index)s is invalid: %(error)s"),
                    code="website_url_invalid",
                    params={"index": idx, "error": str(e)},
                )

            # Validate optional 'label' field
            if "label" in website and not isinstance(website["label"], str):
                raise ValidationError(
                    _("Website label at index %(index)s must be a string"),
                    code="website_label_not_string",
                    params={"index": idx},
                )

            # Check for unexpected fields (optional, can be removed if flexibility is needed)
            allowed_fields = {"url", "label"}
            extra_fields = set(website.keys()) - allowed_fields
            if extra_fields:
                raise ValidationError(
                    _(
                        "Website at index %(index)s has unexpected fields: %(fields)s. "
                        "Allowed fields: %(allowed)s"
                    ),
                    code="website_unexpected_fields",
                    params={
                        "index": idx,
                        "fields": ", ".join(sorted(extra_fields)),
                        "allowed": ", ".join(sorted(allowed_fields)),
                    },
                )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, WebsitesValidator)

    def deconstruct(self):
        """
        Return a 3-tuple of class import path, positional arguments,
        and keyword arguments that can be used to reconstruct this validator.
        """
        return (
            "server.apps.geometries.validators.WebsitesValidator",
            (),
            {},
        )
