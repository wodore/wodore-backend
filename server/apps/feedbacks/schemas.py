"""Pydantic API schemas for feedback (plain models, dmr-compatible)."""

import pydantic
from pydantic import Field


class FeedbackCreate(pydantic.BaseModel):
    """Feedback submission payload."""

    email: str
    subject: str
    message: str
    get_updates: bool
    urls: list[str] | None = Field(None)


class ResponseSchema(pydantic.BaseModel):
    """Feedback submission confirmation."""

    message: str
    id: int
