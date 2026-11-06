"""Feedback endpoint on dmr."""

import pydantic
from dmr import Body, Query, modify
from dmr.routing import path
from pydantic import Field

from django.conf import settings
from django.core.mail import EmailMessage

from server.apps.api.controller import ApiController
from server.apps.api.throttling import FEEDBACK_THROTTLE

from .models import Feedback
from .schemas import FeedbackCreate, ResponseSchema


class FeedbackQuery(pydantic.BaseModel):
    send_email: bool = Field(True, description="Send notification email")


class FeedbackController(ApiController):
    """User feedback submission."""

    @modify(
        operation_id="create_feedback",
        # Public, unauthenticated, stores a row AND sends admin email:
        # brute-force/spam protection before anything else lands on it.
        throttling=[FEEDBACK_THROTTLE],
    )
    def post(
        self,
        parsed_body: Body[FeedbackCreate],
        parsed_query: Query[FeedbackQuery],
    ) -> ResponseSchema:
        """Submit feedback.

        Stored, optionally mailed to the admins."""
        payload = parsed_body
        if payload.urls is None:
            payload.urls = []
        if not payload.subject:
            payload.subject = f"Message from {payload.email}"
        feedback = Feedback.objects.create(**payload.model_dump())
        if parsed_query.send_email:
            email = payload.email
            subject = f"[Feedback #{feedback.id}]: {payload.subject} ({email})"
            no_reply = None
            urls = payload.urls
            body = payload.message.replace("\n", "<br/>")
            text = f"<h2>{payload.subject}</h2>"
            text += f"<p>{body}</p>"
            if urls:
                text += "<h4>URLs:</h4><ul>"
                for url in urls:
                    text += f'<li><a href="{url}">{url}</a></li>'
                text += "</ul>"
            text += f'<p><i>from <a href="mailto:{email}">{email}</a>.</i>'
            text += (
                f'<hr/><p><a href="{settings.DJANGO_ADMIN_URL}/feedbacks/feedback/'
                f'{feedback.id}/change/">edit message</a><br/>'
                f"<small>{feedback.created}</small></p>"
            )
            recipient = [
                a[1] if len(a) > 1 else a[0] for a in settings.DJANGO_ADMIN_EMAILS if a
            ]
            msg = EmailMessage(
                subject=subject,
                body=text,
                from_email=no_reply,
                to=recipient,
                reply_to=[email],
            )
            msg.content_subtype = "html"
            msg.send()
        return ResponseSchema(message="Thank you for the feedback", id=feedback.id)


paths = [
    path("", FeedbackController.as_view(), name="create_feedback"),
]
