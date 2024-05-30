from ninja import ModelSchema, Field

from .models import Feedback


class FeedbackCreate(ModelSchema):
    urls: list[str] | None = Field(None)
    email: str
    subject: str
    message: str

    class Meta:
        model = Feedback
        fields = ("email", "subject", "message")
