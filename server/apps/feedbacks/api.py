import email
from re import sub

from ninja import Query, Router

from django.conf import settings
from django.core.mail import send_mail

# from ninja.errors import HttpError
from django.http import HttpRequest

from server.apps.api.schemas import ResponseSchema

from .models import Feedback
from .schemas import FeedbackCreate
from django.core.mail import EmailMessage

router = Router()


@router.post("/", response=ResponseSchema)
def create_feedback(request: HttpRequest, payload: FeedbackCreate, send_email: bool = True) -> ResponseSchema:
    if payload.urls is None:
        payload.urls = []
    if not payload.subject:
        payload.subject = f"Message from {payload.email}"
    feedback = Feedback.objects.create(**payload.model_dump())
    if send_email:
        email = payload.email
        subject = f"[Feedback #{feedback.id}]: {payload.subject} ({email})"
        # no_reply = (
        # f"{email.split('@')[0]} [NoReply] <{settings.DEFAULT_FROM_EMAIL}>"  # "no-reply@wodore.com"  # payload.email
        # )
        no_reply = None  # email.replace("@", "AT") + "@wodore.com"
        urls = payload.urls
        text = f"<h2>{payload.subject}</h2>"
        text += f"<p>{payload.message}</p>"
        if urls:
            text += "<h4>URLs:</h4><ul>"
            for url in urls:
                text += f'<li><a href="{url}">{url}</a></li>'
            text += "</ul>"
        text += f'<p><i>from <a href="mailto:{email}">{email}</a>.</i>'
        text += f'<hr/><p><a href="{settings.MAIN_URL}/feedbacks/feedback/{feedback.id}/change/">edit message</a><br/><small>{feedback.created}</small></p>'
        recipient = [a[1] for a in settings.ADMINS]
        print(recipient)
        print(text)
        msg = EmailMessage(subject=subject, body=text, from_email=no_reply, to=recipient, reply_to=[email])
        msg.content_subtype = "html"
        msg.send()
    return ResponseSchema(message="Thank you for the feedback", id=feedback.id)
