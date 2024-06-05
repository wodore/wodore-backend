from ninja import ModelSchema, Field

from .models import Feedback


class FeedbackCreate(ModelSchema):
    urls: list[str] | None = Field(None)
    email: str
    subject: str
    message: str
    get_updates: bool

    class Meta:
        model = Feedback
        fields = ("email", "subject", "message", "get_updates")
