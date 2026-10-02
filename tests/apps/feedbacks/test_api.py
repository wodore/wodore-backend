"""Tests for feedbacks API endpoints (submission + throttling)."""

import pytest

pytestmark = pytest.mark.django_db


class TestFeedbackThrottling:
    def test_sixth_request_within_a_minute_is_throttled(self, client):
        """Public endpoint that stores a row and mails admins: 5/min/IP."""
        payload = {
            "email": "someone@example.com",
            "subject": "hi",
            "message": "hello",
            "get_updates": False,
        }
        for _ in range(5):
            response = client.post(
                "/v1/feedback/", payload, content_type="application/json"
            )
            assert response.status_code in {200, 201, 503}  # 201 = dmr POST default
        sixth = client.post("/v1/feedback/", payload, content_type="application/json")
        assert sixth.status_code == 429
        assert "Retry-After" in sixth.headers
