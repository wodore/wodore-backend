from typing import final

import pytest
from hypothesis import given
from hypothesis.extra import django

from server.apps.huts.models import Hut


@final
@pytest.mark.skip("Does not work yet")
class TestBlogPost(django.TestCase):
    """This is a property-based test that ensures model correctness."""

    @given(django.from_model(Hut))
    def test_model_properties(self, instance: Hut) -> None:
        """Tests that instance can be saved and has correct representation."""
        instance.save()

        assert instance.id > 0
        assert len(str(instance)) <= 20
