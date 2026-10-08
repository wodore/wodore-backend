"""Throttling of the availability endpoints (openspec: api-throttling).

Behavior is exercised through a probe controller wired exactly like the
real ones (same ``ClientIp`` key, same shared ``throttling`` backend) but
with a small limit, so tests don't need 120+ requests or seeded counters.
The real controllers' wiring is pinned by introspection: they must carry
the settings-driven stacked throttles.
"""

import json
from collections.abc import Callable

from dmr import modify
from dmr.throttling import Rate, SyncThrottle

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponseBase
from django.test import RequestFactory

from server.apps.api.controller import ApiController
from server.apps.api.throttling import (
    AVAILABILITY_BURST_THROTTLE,
    AVAILABILITY_DAILY_THROTTLE,
    ClientIp,
    throttle_backend,
)
from server.apps.availability.api import (
    HutAvailabilityCurrentController,
    HutAvailabilityGeojsonController,
    HutAvailabilityTrendController,
)

_PROBE_LIMIT = 2


def _probe_view() -> Callable[..., HttpResponseBase]:
    """A minimal controller throttled like the availability endpoints."""

    class ProbeController(ApiController):
        @modify(
            operation_id="probe_throttle_client_ip",
            throttling=[
                SyncThrottle(
                    _PROBE_LIMIT,
                    Rate.minute,
                    cache_key=ClientIp(),
                    backend=throttle_backend(),
                ),
            ],
        )
        def get(self) -> dict[str, bool]:
            """Probe endpoint: answers {"ok": true} until throttled."""

            return {"ok": True}

    return ProbeController.as_view()


def _request(
    remote_addr: str = "127.0.0.1",
    forwarded_for: str | None = None,
) -> WSGIRequest:
    request = RequestFactory().get("/probe")
    request.META["REMOTE_ADDR"] = remote_addr
    if forwarded_for is not None:
        request.META["HTTP_X_FORWARDED_FOR"] = forwarded_for
    return request


class TestClientIpBuckets:
    def test_burst_trips_after_limit(self):
        """Limit 2/min: first two pass, third answers 429 + headers + body."""
        view = _probe_view()
        ip = "203.0.113.1"  # unique per test: counters share the cache
        for _ in range(_PROBE_LIMIT):
            response = view(_request(forwarded_for=ip))
            assert response.status_code == 200
        throttled = view(_request(forwarded_for=ip))
        assert throttled.status_code == 429
        assert "Retry-After" in throttled.headers
        assert throttled.headers["X-RateLimit-Limit"] == str(_PROBE_LIMIT)
        assert throttled.headers["X-RateLimit-Remaining"] == "0"
        body = json.loads(throttled.content)
        assert body["code"] == "throttled"
        assert body["detail"]

    def test_distinct_forwarded_clients_get_separate_buckets(self):
        """One tripped client must not throttle another (per-IP buckets)."""
        view = _probe_view()
        for _ in range(_PROBE_LIMIT):
            assert view(_request(forwarded_for="203.0.113.2")).status_code == 200
        assert view(_request(forwarded_for="203.0.113.2")).status_code == 429
        # A different client is unaffected:
        assert view(_request(forwarded_for="203.0.113.3")).status_code == 200

    def test_first_forwarded_entry_wins(self):
        """ "X-Forwarded-For: client, proxy" keys on the client address."""
        view = _probe_view()
        assert view(_request(forwarded_for="203.0.113.4, 10.0.0.9")).status_code == (
            200
        )
        # Same client entry (different proxy hop) shares the bucket:
        for _ in range(_PROBE_LIMIT - 1):
            assert (
                view(_request(forwarded_for="203.0.113.4, 10.0.0.8")).status_code == 200
            )
        assert view(_request(forwarded_for="203.0.113.4")).status_code == 429

    def test_no_forward_header_falls_back_to_remote_addr(self):
        """Direct requests (no XFF) key on REMOTE_ADDR."""
        view = _probe_view()
        assert view(_request(remote_addr="198.51.100.7")).status_code == 200
        assert view(_request(remote_addr="198.51.100.7")).status_code == 200
        assert view(_request(remote_addr="198.51.100.7")).status_code == 429
        # Different direct client unaffected:
        assert view(_request(remote_addr="198.51.100.8")).status_code == 200


class TestAvailabilityWiring:
    """The three availability controllers carry the stacked throttles."""

    THROTTLED_CONTROLLERS = (
        HutAvailabilityGeojsonController,
        HutAvailabilityCurrentController,
        HutAvailabilityTrendController,
    )

    def test_controllers_declare_the_stacked_profile(self):
        for controller in self.THROTTLED_CONTROLLERS:
            throttling = controller.api_endpoints["GET"].metadata.throttling
            assert throttling == [
                AVAILABILITY_BURST_THROTTLE,
                AVAILABILITY_DAILY_THROTTLE,
            ], controller.__name__

    def test_limits_follow_settings(self):
        from django.conf import settings

        assert AVAILABILITY_BURST_THROTTLE.max_requests == (
            settings.API_THROTTLE_AVAILABILITY_BURST_PER_MIN
        )
        assert AVAILABILITY_BURST_THROTTLE.duration_in_seconds == int(Rate.minute)
        assert AVAILABILITY_DAILY_THROTTLE.max_requests == (
            settings.API_THROTTLE_AVAILABILITY_DAILY
        )
        assert AVAILABILITY_DAILY_THROTTLE.duration_in_seconds == int(Rate.day)

    def test_throttles_use_client_ip_on_the_shared_alias(self):
        for throttle in (AVAILABILITY_BURST_THROTTLE, AVAILABILITY_DAILY_THROTTLE):
            assert isinstance(throttle.cache_key, ClientIp)
            assert throttle._backend.cache_name == "throttling"
