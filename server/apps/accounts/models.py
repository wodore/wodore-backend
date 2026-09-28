"""Custom user model: email is the identity (spec: account-management).

Email is the login identifier everywhere (allauth, admin, createsuperuser),
so it carries the unique constraint the default ``auth.User`` never had.
The ``username`` field is dropped — the legacy Zitadel-synced accounts used
numeric Zitadel IDs there, which no longer matter.

Introduced while there is no production user base (the cheapest moment);
existing dev/test databases are migrated in ``0001_initial`` (rows copied
from ``auth_user``, primary keys preserved).
"""

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    username = None
    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    def __str__(self) -> str:
        return self.email
