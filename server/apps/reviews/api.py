"""dmr controllers for hut reviews (openspec: reviews-mangrove D3).

One operation per path (the E003/E004 versioning invariant keys URL
names 1:1 to operation ids — no path carries two HTTP methods). Reads
are anonymous, throttled, short-TTL cacheable; writes live on the
``ReviewsWriteController`` base (401 + ``private, no-store``, session
OR bearer caller resolution — same semantics as the ``/v1/my/``
namespace base in ``server.apps.external_links.api``).
"""

from http import HTTPStatus
from typing import Any, ClassVar, override

import pydantic
from dmr import APIError, Body, HeaderSpec, Path, Query, ResponseSpec, modify
from dmr.routing import path
from dmr.throttling import Rate

from django.conf import settings
from django.http import HttpRequest, HttpResponseBase

from server.apps.api.auth import AuthBearer
from server.apps.api.controller import (
    ApiController,
    ErrorDetail,
    cache_headers,
)
from server.apps.api.error_codes import ErrorCode
from server.apps.api.throttling import ClientIp, SyncThrottle, throttle_backend

from . import services
from .schemas import (
    BatchSummaryEnvelope,
    BatchSummaryQuery,
    IdentityExportOut,
    IdentityImportIn,
    MergeRequestOut,
    MyReviewOut,
    PhotoUploadResponse,
    ReportOut,
    ReviewEditIn,
    ReviewListQuery,
    ReviewMergeRequestIn,
    ReviewOut,
    ReviewReplyIn,
    ReviewReportIn,
    ReviewsEnvelope,
    ReviewSubmitIn,
    ReviewSummaryOut,
)

#: Bound on the batch summary (map badges): one slug list, ≤50 entries.
BATCH_MAX_SLUGS = 50

#: Anonymous read throttle: burst per minute + daily volume brake
#: (upstream-amplification guard, design D10).
_REVIEWS_BURST_THROTTLE = SyncThrottle(
    settings.ORA_THROTTLE_READ_BURST_PER_MIN,
    Rate.minute,
    cache_key=ClientIp(),
    backend=throttle_backend(),
)
_REVIEWS_DAILY_THROTTLE = SyncThrottle(
    settings.ORA_THROTTLE_READ_DAILY,
    Rate.day,
    cache_key=ClientIp(),
    backend=throttle_backend(),
)
#: Batch summary + abuse reports: tighter burst.
_REVIEWS_BATCH_THROTTLE = SyncThrottle(
    settings.ORA_THROTTLE_BATCH_PER_MIN,
    Rate.minute,
    cache_key=ClientIp(),
    backend=throttle_backend(),
)

#: Extra error responses raised from the endpoint bodies (dmr's response
#: validation only allows statuses it knows about — same pattern as the
#: availability controllers' ``extra_responses``).
_UPSTREAM_503 = ResponseSpec(
    ErrorDetail,
    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
    description="Review service (Mangrove upstream) unavailable. Retry later.",
)
_FORBIDDEN_403 = ResponseSpec(
    ErrorDetail,
    status_code=HTTPStatus.FORBIDDEN,
    description="The review belongs to another reviewer.",
)
_QUOTA_429 = ResponseSpec(
    ErrorDetail,
    status_code=HTTPStatus.TOO_MANY_REQUESTS,
    description="Review write quota exceeded (see Retry-After).",
    headers={"Retry-After": HeaderSpec(required=False, skip_validation=True)},
)


class HutReviewPath(pydantic.BaseModel):
    """Hut-scoped review path."""

    slug: str = pydantic.Field(description="Hut slug")


class HutReviewSignaturePath(HutReviewPath):
    """Hut-scoped review path with a target signature."""

    signature: str = pydantic.Field(description="Mangrove review signature")


class ReviewsListController(ApiController):
    """A hut's reviews (public, proxied, filtered)."""

    @modify(
        operation_id="get_hut_reviews",
        headers=cache_headers(settings.ORA_PUBLIC_MAX_AGE),
        throttling=[_REVIEWS_BURST_THROTTLE, _REVIEWS_DAILY_THROTTLE],
        extra_responses=[_UPSTREAM_503],
    )
    def get(
        self,
        parsed_path: Path[HutReviewPath],
        parsed_query: Query[ReviewListQuery],
    ) -> ReviewsEnvelope:
        """Get a hut's reviews.

        Open Mangrove reviews of this hut, newest first, locally
        paginated. Published under CC-BY-4.0 by the Open Reviews
        Association (see `attribution`)."""
        hut = services.resolve_hut(parsed_path.slug)
        return services.list_reviews(hut, parsed_query.limit, parsed_query.offset)


class HutReviewSummaryController(ApiController):
    """A hut's locally computed review aggregate (public)."""

    @modify(
        operation_id="get_hut_reviews_summary",
        headers=cache_headers(settings.ORA_PUBLIC_MAX_AGE),
        throttling=[_REVIEWS_BURST_THROTTLE, _REVIEWS_DAILY_THROTTLE],
        extra_responses=[_UPSTREAM_503],
    )
    def get(
        self,
        parsed_path: Path[HutReviewPath],
    ) -> ReviewSummaryOut:
        """Get a hut's review summary.

        Count, mean rating and positives computed locally over the
        visible (blacklist-filtered) reviews."""
        hut = services.resolve_hut(parsed_path.slug)
        return services.summary_for_hut(hut)


class ReviewsBatchSummaryController(ApiController):
    """Batch aggregates for map badges (public, bounded)."""

    @modify(
        operation_id="get_reviews_summary_batch",
        headers=cache_headers(settings.ORA_PUBLIC_MAX_AGE),
        throttling=[_REVIEWS_BATCH_THROTTLE, _REVIEWS_DAILY_THROTTLE],
        extra_responses=[_UPSTREAM_503],
    )
    def get(
        self,
        parsed_query: Query[BatchSummaryQuery],
    ) -> BatchSummaryEnvelope:
        """Get review summaries for multiple huts.

        One locally computed aggregate per slug (≤50, sorted,
        deduplicated) for map badges; zeroed for huts without reviews."""
        slugs = parsed_query.slugs.split(",")
        if len({s.strip() for s in slugs}) > BATCH_MAX_SLUGS:
            raise APIError(
                {
                    "code": ErrorCode.validation_error,
                    "detail": f"At most {BATCH_MAX_SLUGS} hut slugs per batch.",
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )
        return services.batch_summary(slugs)


class ReviewsWriteController(ApiController):
    """Auth gate for review writes (session OR bearer; 401, no-store).

    Mirrors ``MyApiController`` (``server.apps.external_links.api``):
    ``security=`` documents bearer auth in OpenAPI, the runtime
    enforcement lives HERE — plus bearer-token caller resolution
    (``request.auth['sub']`` → user) so API clients work without a
    session.
    """

    _security_default: ClassVar[Any] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("security", [AuthBearer()])
        super().__init__(*args, **kwargs)

    @override
    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        caller = services.caller_from_request(request)
        response: HttpResponseBase
        if caller is None:
            response = self.to_response(
                {
                    "code": ErrorCode.not_authenticated,
                    "detail": "authentication required",
                },
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        else:
            request.reviews_caller = caller  # type: ignore[attr-defined]
            response = super().dispatch(request, *args, **kwargs)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @property
    def caller(self) -> Any:
        """The resolved caller user (set by ``dispatch``)."""
        return self.request.reviews_caller  # type: ignore[no-any-return]


class ReviewSubmitController(ReviewsWriteController):
    """Submit a review for a hut (authenticated, signed server-side)."""

    @modify(
        operation_id="submit_hut_review",
        status_code=HTTPStatus.CREATED,
        extra_responses=[_QUOTA_429, _UPSTREAM_503],
    )
    def post(
        self,
        parsed_path: Path[HutReviewPath],
        parsed_body: Body[ReviewSubmitIn],
    ) -> ReviewOut:
        """Submit a hut review.

        The review is signed with your Wodore reviewer key and
        published to the open Mangrove dataset (CC-BY-4.0, Open Reviews
        Association terms: https://mangrove.reviews/terms). Rating is
        the likelihood to recommend (0–100)."""
        hut = services.resolve_hut(parsed_path.slug)
        from django.utils import translation

        return services.submit_review(
            self.caller, hut, parsed_body, translation.get_language() or "de"
        )


class ReviewEditController(ReviewsWriteController):
    """Edit own review (signed ``edit`` action)."""

    @modify(
        operation_id="edit_hut_review",
        status_code=HTTPStatus.OK,
        extra_responses=[_FORBIDDEN_403, _QUOTA_429, _UPSTREAM_503],
    )
    def post(
        self,
        parsed_path: Path[HutReviewSignaturePath],
        parsed_body: Body[ReviewEditIn],
    ) -> ReviewOut:
        """Edit a hut review.

        Relays a signed Mangrove ``edit`` action against the review's
        ``signature`` (only your own reviews)."""
        hut = services.resolve_hut(parsed_path.slug)
        return services.edit_review(
            self.caller, hut, parsed_path.signature, parsed_body
        )


class ReviewDeleteController(ReviewsWriteController):
    """Delete own review (signed ``delete`` action, idempotent)."""

    @modify(
        operation_id="delete_hut_review",
        status_code=HTTPStatus.NO_CONTENT,
        extra_responses=[_FORBIDDEN_403, _QUOTA_429, _UPSTREAM_503],
    )
    def post(
        self,
        parsed_path: Path[HutReviewSignaturePath],
    ) -> None:
        """Delete a hut review.

        Relays a signed Mangrove ``delete`` action (only your own
        reviews); already-deleted targets count as deleted."""
        hut = services.resolve_hut(parsed_path.slug)
        services.delete_review(self.caller, hut, parsed_path.signature)


class ReviewReportController(ReviewsWriteController):
    """Report abuse of any review on this hut (signed action)."""

    @modify(
        operation_id="report_hut_review",
        status_code=HTTPStatus.OK,
        throttling=[_REVIEWS_BATCH_THROTTLE],
        extra_responses=[_UPSTREAM_503],
    )
    def post(
        self,
        parsed_path: Path[HutReviewSignaturePath],
        parsed_body: Body[ReviewReportIn],
    ) -> ReportOut:
        """Report an abusive hut review.

        Relays a signed Mangrove ``report_abuse`` action; the reason is
        required and forwarded to the dataset moderators."""
        hut = services.resolve_hut(parsed_path.slug)
        return services.report_review(
            self.caller, hut, parsed_path.signature, parsed_body
        )


class ReviewReplyController(ReviewsWriteController):
    """Reply to a review (signed review with an ``urn:maresi`` subject)."""

    @modify(
        operation_id="reply_hut_review",
        status_code=HTTPStatus.CREATED,
        extra_responses=[_QUOTA_429, _UPSTREAM_503],
    )
    def post(
        self,
        parsed_path: Path[HutReviewSignaturePath],
        parsed_body: Body[ReviewReplyIn],
    ) -> ReviewOut:
        """Reply to a hut review.

        Signs a Mangrove review whose subject references the parent
        review (``urn:maresi:{signature}``) — a reply plus an optional
        helpfulness rating of the parent."""
        hut = services.resolve_hut(parsed_path.slug)
        return services.reply_review(
            self.caller, hut, parsed_path.signature, parsed_body
        )


class ReviewRepliesController(ApiController):
    """Replies to one review (public, cached per signature)."""

    @modify(
        operation_id="get_hut_review_replies",
        headers=cache_headers(settings.ORA_PUBLIC_MAX_AGE),
        throttling=[_REVIEWS_BURST_THROTTLE, _REVIEWS_DAILY_THROTTLE],
        extra_responses=[_UPSTREAM_503],
    )
    def get(
        self,
        parsed_path: Path[HutReviewSignaturePath],
    ) -> ReviewsEnvelope:
        """List replies to a hut review.

        Other reviewers' replies and helpfulness ratings of this
        review, newest first."""
        hut = services.resolve_hut(parsed_path.slug)
        return services.list_replies(hut, parsed_path.signature)


class ReviewMergeRequestController(ReviewsWriteController):
    """File a merge request for staff (no Mangrove write)."""

    @modify(
        operation_id="create_review_merge_request",
        status_code=HTTPStatus.CREATED,
        throttling=[_REVIEWS_BATCH_THROTTLE],
    )
    def post(
        self,
        parsed_path: Path[HutReviewPath],
        parsed_body: Body[ReviewMergeRequestIn],
    ) -> MergeRequestOut:
        """Request a review merge.

        Files a merge request (target plus context) for staff review —
        an admin performs the actual subject equivalence later."""
        hut = services.resolve_hut(parsed_path.slug)
        request_row = services.create_merge_request(
            self.caller,
            hut,
            parsed_body.target,
            parsed_body.note,
            parsed_body.link or "",
        )
        return MergeRequestOut(id=request_row.pk, state=request_row.state)


class MyReviewsController(ReviewsWriteController):
    """The caller's own reviews (private, never cached)."""

    @modify(operation_id="get_my_reviews", extra_responses=[_UPSTREAM_503])
    def get(self) -> list[MyReviewOut]:
        """List my reviews.

        Reviews authored by your Wodore reviewer key (including
        foreign-subject ones after a future key import), annotated with
        the Wodore hut slug where resolvable."""
        return services.my_reviews(self.caller)


class ReviewPhotoUploadController(ReviewsWriteController):
    """Upload review photos to the Mangrove file server (relay, no storage)."""

    @modify(
        operation_id="upload_review_photos",
        status_code=HTTPStatus.CREATED,
        throttling=[_REVIEWS_BATCH_THROTTLE],
        extra_responses=[_UPSTREAM_503],
    )
    def post(self) -> PhotoUploadResponse:
        """Upload photos for a review.

        Relays JPEG/PNG/GIF/WebP images to the Mangrove file server
        (≤5 photos, ≤4.5 MB total). Returns the public
        ``files.mangrove.reviews`` URLs to include in the review's
        ``images[].src``. Wodore stores nothing — photos are
        content-addressed and immutable upstream; unlisted photos are
        deleted after a day.
        """
        from . import services
        from .schemas import PhotoUploadOut

        files: list[tuple[str, bytes, str]] = []
        for uploaded in self.request.FILES.getlist("files"):
            files.append(
                (uploaded.name or "photo", uploaded.read(), uploaded.content_type or "")
            )
        urls = services.upload_review_photos(files)
        return PhotoUploadResponse(images=[PhotoUploadOut(src=url) for url in urls])


class ReviewIdentityExportController(ReviewsWriteController):
    """Export the caller's review identity (private JWK)."""

    @modify(operation_id="export_review_identity")
    def get(self) -> IdentityExportOut:
        """Export my review identity as a JWK.

        Returns the private EC P-256 JWK string (compatible with
        MapComplete and mangrove.reviews import/export). This is the
        user's private review identity — handle with care. Only
        available after the first review submission.
        """
        data = services.export_identity(self.caller)
        return IdentityExportOut(**data)


class ReviewIdentityImportController(ReviewsWriteController):
    """Import a review identity (JWK) to replace the caller's key."""

    @modify(operation_id="import_review_identity", status_code=HTTPStatus.OK)
    def post(
        self,
        parsed_body: Body[IdentityImportIn],
    ) -> IdentityExportOut:
        """Import a review identity (JWK).

        Replaces the caller's current review key with the imported one.
        Reviews signed with the imported key become editable/deletable
        from Wodore. Reviews signed with a previous key become
        unmanageable (re-import the old JWK to manage them).
        """
        result = services.import_identity(self.caller, parsed_body.jwk)
        return IdentityExportOut(
            jwk=parsed_body.jwk,
            kid=result["kid"],
            nickname=result.get("nickname"),
        )


#: Top-level routes — mounted under ``reviews/`` by ``api_v1.py``.
paths = [
    path(
        "summary",
        ReviewsBatchSummaryController.as_view(),
        name="get_reviews_summary_batch",
    ),
    path(
        "images",
        ReviewPhotoUploadController.as_view(),
        name="upload_review_photos",
    ),
]

#: Hut-scoped routes — mounted under ``huts/`` by ``api_v1.py``.
hut_paths = [
    path(
        "<str:slug>/reviews",
        ReviewsListController.as_view(),
        name="get_hut_reviews",
    ),
    path(
        "<str:slug>/reviews/summary",
        HutReviewSummaryController.as_view(),
        name="get_hut_reviews_summary",
    ),
    path(
        "<str:slug>/reviews/submit",
        ReviewSubmitController.as_view(),
        name="submit_hut_review",
    ),
    path(
        "<str:slug>/reviews/<str:signature>/edit",
        ReviewEditController.as_view(),
        name="edit_hut_review",
    ),
    path(
        "<str:slug>/reviews/<str:signature>/delete",
        ReviewDeleteController.as_view(),
        name="delete_hut_review",
    ),
    path(
        "<str:slug>/reviews/<str:signature>/report",
        ReviewReportController.as_view(),
        name="report_hut_review",
    ),
    path(
        "<str:slug>/reviews/<str:signature>/reply",
        ReviewReplyController.as_view(),
        name="reply_hut_review",
    ),
    path(
        "<str:slug>/reviews/<str:signature>/replies",
        ReviewRepliesController.as_view(),
        name="get_hut_review_replies",
    ),
    path(
        "<str:slug>/reviews/merge-request",
        ReviewMergeRequestController.as_view(),
        name="create_review_merge_request",
    ),
]

#: User-scoped route — mounted under ``my/`` by ``api_v1.py``.
my_paths = [
    path("reviews", MyReviewsController.as_view(), name="get_my_reviews"),
    path(
        "reviews/identity",
        ReviewIdentityExportController.as_view(),
        name="export_review_identity",
    ),
    path(
        "reviews/identity/import",
        ReviewIdentityImportController.as_view(),
        name="import_review_identity",
    ),
]
