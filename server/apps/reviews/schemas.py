"""Shared pydantic DTOs for the reviews API (request + response).

Lives outside ``api.py`` so ``services.py`` can construct responses
without importing the controller layer.
"""

import pydantic
from pydantic import Field

#: Envelope attribution for the open dataset (design D9).
LICENSE = "CC-BY-4.0"
ATTRIBUTION = "https://mangrove.reviews"

_EXPERIENCE_CONTEXTS = ("business", "family", "couple", "friends", "solo")
_LANG_RE = r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{1,8})*$"


class ReviewImageIn(pydantic.BaseModel):
    """MaReSt ``images[]`` input item."""

    model_config = pydantic.ConfigDict(extra="forbid")

    src: str = Field(description="Public https URL of the image")
    label: str | None = Field(
        None, max_length=50, description="Alt text for the image (≤50 chars)"
    )

    @pydantic.field_validator("src")
    @classmethod
    def _src_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            msg = "image src must be an https URL"
            raise ValueError(msg)
        return value


class ReviewSubmitIn(pydantic.BaseModel):
    """Review submission body (rating and/or opinion; unknown keys 4xx)."""

    model_config = pydantic.ConfigDict(extra="forbid")

    rating: int | None = Field(
        None, ge=0, le=100, description="Likelihood to recommend, 0–100"
    )
    opinion: str | None = Field(
        None, max_length=1000, description="Review text (≤1000 chars)"
    )
    images: list[ReviewImageIn] | None = Field(
        None, max_length=5, description="Up to 5 images"
    )
    nickname: str | None = Field(None, max_length=50)
    language: str | None = Field(None, max_length=35, pattern=_LANG_RE)
    experience_context: str | None = Field(None, max_length=20)
    is_personal_experience: bool | None = Field(
        None, description="Direct personal experience (flag sent only when true)"
    )
    is_affiliated: bool | None = Field(
        None,
        description="Affiliation with the hut's operator (flag sent only when true)",
    )

    @pydantic.field_validator("experience_context")
    @classmethod
    def _context_known(cls, value: str | None) -> str | None:
        if value is not None and value not in _EXPERIENCE_CONTEXTS:
            msg = f"experience_context must be one of {', '.join(_EXPERIENCE_CONTEXTS)}"
            raise ValueError(msg)
        return value

    @pydantic.field_validator("is_personal_experience", "is_affiliated")
    @classmethod
    def _flags_only_true(cls, value: bool | None) -> bool | None:
        # MaReSt: flag fields MUST equal true when present.
        if value is False:
            msg = "flag fields can only be sent as true (omit them otherwise)"
            raise ValueError(msg)
        return value

    @pydantic.model_validator(mode="after")
    def _rating_or_opinion(self) -> "ReviewSubmitIn":
        if self.rating is None and self.opinion is None:
            msg = "at least one of rating or opinion is required"
            raise ValueError(msg)
        return self


class ReviewEditIn(ReviewSubmitIn):
    """Edit body: at least one of rating/opinion present."""


class ReviewReportIn(pydantic.BaseModel):
    """Abuse report body: the reason is required."""

    model_config = pydantic.ConfigDict(extra="forbid")

    opinion: str = Field(max_length=1000, description="Reason for the report")


class ReviewReplyIn(pydantic.BaseModel):
    """Reply body: rating (helpfulness) and/or opinion (text) + images."""

    model_config = pydantic.ConfigDict(extra="forbid")

    rating: int | None = Field(
        None, ge=0, le=100, description="Helpfulness rating of the parent review"
    )
    opinion: str | None = Field(None, max_length=1000, description="Reply text")
    images: list[ReviewImageIn] | None = Field(
        None, max_length=5, description="Up to 5 images (https URLs)"
    )

    @pydantic.model_validator(mode="after")
    def _rating_or_opinion(self) -> "ReviewReplyIn":
        if self.rating is None and self.opinion is None:
            msg = "at least one of rating or opinion is required"
            raise ValueError(msg)
        return self


class ReviewMergeRequestIn(pydantic.BaseModel):
    """Merge-request body: a target identifier plus context."""

    model_config = pydantic.ConfigDict(extra="forbid")

    target: str = Field(
        max_length=255, description="Subject URI, hut slug or URL to merge with"
    )
    note: str = Field(
        default="", max_length=2000, description="Why these reviews belong together"
    )
    link: str | None = Field(
        None, max_length=500, description="Supporting link (e.g. the other listing)"
    )


class ReviewListQuery(pydantic.BaseModel):
    """Local pagination of the proxied review list."""

    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)


class BatchSummaryQuery(pydantic.BaseModel):
    """Batch summary: bounded, canonicalized slug list."""

    slugs: str = Field(
        description="Comma-separated hut slugs (≤50, deduplicated and sorted)"
    )


class ReviewImageOut(pydantic.BaseModel):
    """Served image (allowlist-filtered)."""

    src: str = Field(description="Image URL (https, allowlisted host)")
    label: str | None = Field(None, description="Alt text")


class ReviewOut(pydantic.BaseModel):
    """One served review (Mangrove or a read-only provider)."""

    signature: str = Field(description="Review signature (maresi id or provider id)")
    rating: int | None = Field(None, description="0–100 likelihood to recommend")
    opinion: str | None = Field(None, description="Review text")
    nickname: str | None = Field(None, description="Reviewer nickname")
    language: str | None = Field(None, description="Language of the opinion (BCP 47)")
    experience_context: str | None = Field(None)
    is_personal_experience: bool = Field(False)
    is_affiliated: bool = Field(False)
    images: list[ReviewImageOut] = Field(default_factory=list)
    created: str = Field(description="Issuance time (ISO 8601, UTC)")
    source: str = Field(
        default="mangrove", description="Review source (mangrove | refuges.info)"
    )
    license: str = Field(
        default="CC-BY-4.0",
        description="License of this review's content (SPDX / CC label)",
    )
    link: str | None = Field(
        None, description="Attribution link to the review's source page"
    )


class ReviewsEnvelope(pydantic.BaseModel):
    """Collection envelope with dataset license/attribution."""

    data: list[ReviewOut]
    count: int = Field(description="Total visible reviews (after filters)")
    license: str = Field(description="Dataset license (SPDX)")
    attribution: str = Field(description="Dataset attribution URL")


class ReviewSummaryOut(pydantic.BaseModel):
    """Locally computed aggregate (design D6)."""

    slug: str
    count: int = Field(description="Visible reviews")
    rating_count: int = Field(description="Reviews carrying a rating")
    rating_mean: float | None = Field(
        None, description="Mean rating over rated reviews"
    )
    positive_count: int = Field(description="Ratings above 50")
    opinion_count: int = Field(description="Reviews carrying an opinion")


class BatchSummaryEnvelope(pydantic.BaseModel):
    data: list[ReviewSummaryOut]
    count: int


class MyReviewOut(ReviewOut):
    """Own review annotated with the Wodore hut (absent for foreign subjects)."""

    hut_slug: str | None = Field(None, description="Wodore hut slug, when resolvable")


class ReportOut(pydantic.BaseModel):
    status: str = Field(description="Report relay status")


class MergeRequestOut(pydantic.BaseModel):
    id: int = Field(description="Merge request id")
    state: str = Field(description="Review state (new/done/rejected)")


class PhotoUploadOut(pydantic.BaseModel):
    """Uploaded photo: the src to include in the review's images[]."""

    src: str = Field(
        description="Public URL on files.mangrove.reviews (content-addressed, immutable)"
    )


class PhotoUploadResponse(pydantic.BaseModel):
    images: list[PhotoUploadOut] = Field(description="Uploaded photos, upload order")
