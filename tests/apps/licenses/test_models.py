"""The license slug field must accept SPDX-style slugs containing dots.

Real license ids produced by the importers are dotted (``cc-by-4.0``,
``cc-by-nc-nd-3.0``, …) and staging data already contains ``cc-by-4.0`` —
the model's custom validator allows dots, but Django's ``SlugField`` also
runs its *default* ``validate_slug`` (dots rejected). ``LicenseSlugField``
replaces the defaults; these tests pin that.
"""

from typing import Any, cast

import pytest

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, validate_slug
from django.db import models

from server.apps.licenses.models import License


@pytest.mark.django_db()
def test_slug_with_dot_is_valid():
    """A dotted slug like ``cc-by-4.0`` passes full model validation."""
    license = License(slug="cc-by-4.0", name_en="CC BY 4.0")
    license.full_clean()  # raises if the slug were rejected


@pytest.mark.django_db()
@pytest.mark.parametrize("slug", ["cc by 4.0", "cc/by", "cc!by"])
def test_slug_with_invalid_chars_is_rejected(slug: str):
    with pytest.raises(ValidationError):
        License(slug=slug).full_clean()


def test_default_slug_validator_is_replaced():
    """Django's dot-rejecting ``validate_slug`` must not run for the slug."""
    field = cast("models.SlugField[Any, Any]", License._meta.get_field("slug"))
    assert validate_slug not in field.validators
    validator = cast(RegexValidator, field.validators[0])
    assert "dot" in validator.message.lower()
