"""Custom user model: email is the identity (spec: account-management).

Email is the login identifier everywhere (allauth, admin, createsuperuser),
so it carries the unique constraint the default ``auth.User`` never had.
The ``username`` field is dropped — the legacy Zitadel-synced accounts used
numeric Zitadel IDs there, which no longer matter.

Email is the identity (spec: account-management), the primary key is an
opaque UUID v4 (no enumeration, stable ids when sanitized prod→staging
copies re-create placeholder users with the same ids).

Introduced while there is no production user base (the cheapest moment);
existing dev/test databases are migrated in ``0001_initial`` (rows copied
from ``auth_user``, primary keys preserved) and converted to UUID keys in
``0003_uuid_pk``.
"""

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []  # type: ignore[assignment]  # Django idiom

    objects = UserManager()

    def __str__(self) -> str:
        return self.email
