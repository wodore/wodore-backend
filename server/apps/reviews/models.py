"""Reviewer models: per-account Mangrove key custody and the submission log.

Design: openspec/changes/reviews-mangrove (D4, D5). Key facts:
(Verified: `pyrefly check server/apps/reviews/models.py` — 0 errors; the
nested `Meta` classes follow the repo-wide TimeStampedModel idiom.)

* One ES256 keypair per user account, minted lazily on first write. The
  private JWK is stored Fernet-encrypted under
  ``settings.MANGROVE_KEY_ENCRYPTION_KEYS`` (MultiFermint-style
  add-new-keep-old rotation). ``kid`` is the whitespace-normalized
  single-line PEM the Mangrove standard compares by.
* All user foreign keys are ``PROTECT`` — deleting an account that owns
  reviews must fail loudly instead of destroying the only key able to
  sign ``delete`` actions upstream (the sanctioned path is
  ``reviews_erase_user``).
* ``SubmittedReview`` is append-only: a delete is a NEW ``delete`` action
  row, never a mutation; the erasure command is the one documented
  exception that destroys rows.
"""

import typing as t

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel

if t.TYPE_CHECKING:
    from server.apps.accounts.models import User


def _fernet_keys() -> list[Fernet]:
    """Fernet instances for the configured encryption secrets.

    First entry encrypts (primary); all entries decrypt (rotation keeps
    old secrets decryptable — add-new-keep-old).
    """
    import base64
    import hashlib

    ferns: list[Fernet] = []
    for secret in settings.MANGROVE_KEY_ENCRYPTION_KEYS:
        digest = hashlib.sha256(secret.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
        ferns.append(Fernet(key))
    return ferns


def encrypt_private_jwk(jwk_json: str) -> str:
    """Encrypt a private JWK JSON string for at-rest storage."""
    return MultiFernet(_fernet_keys()).encrypt(jwk_json.encode()).decode()


def decrypt_private_jwk(token: str) -> str:
    """Decrypt an at-rest private JWK JSON string.

    Raises:
        InvalidToken: no configured secret can decrypt the token (the
            encryption secret was lost/rotated away - see design risks).
    """
    return MultiFernet(_fernet_keys()).decrypt(token.encode()).decode()


class ReviewerKey(TimeStampedModel):
    """Server-held Mangrove reviewer keypair of one user account."""

    user: "models.OneToOneField[User]" = models.OneToOneField(  # type: ignore[assignment]  # OneToOneField typing drift vs django-stubs reverse
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewer_key",
        verbose_name=_("User"),
    )
    #: Public key as whitespace-normalized single-line PEM (MaReSt ``kid``
    #: — servers compare PEMs with whitespace removed).
    kid = models.TextField(unique=True, verbose_name=_("Reviewer key (PEM)"))
    #: Fernet-encrypted private JWK JSON (d, x, y, crv, kty).
    private_jwk_encrypted = models.TextField(verbose_name=_("Encrypted private JWK"))

    objects = models.Manager()

    class Meta:  # type: ignore[assignment]  # nested Meta vs abstract base Meta: known checker limitation (Hut.Meta idiom)
        verbose_name = _("Reviewer key")
        verbose_name_plural = _("Reviewer keys")

    def __str__(self) -> str:
        return f"{self.user} {self.kid[:40]}…"

    @property
    def private_jwk(self) -> dict[str, t.Any]:
        """The decrypted private JWK as a dict (never serialized to API).

        Raises:
            RuntimeError: the ciphertext cannot be decrypted under any
                configured secret (lost/rotated-away encryption key).
        """
        import json

        from cryptography.fernet import InvalidToken

        try:
            raw = decrypt_private_jwk(self.private_jwk_encrypted)
            parsed = json.loads(raw)
        except (InvalidToken, ValueError, TypeError) as exc:
            msg = (
                "ReviewerKey cannot be decrypted - the encryption secret "
                "was lost or rotated away (see AGENTS.md § Reviews)."
            )
            raise RuntimeError(msg) from exc
        return t.cast(
            dict[str, t.Any],
            parsed,
        )


def _mint_nickname() -> str:
    """A non-identifying default nickname (never account-derived)."""
    import secrets

    return f"hut-friend-{secrets.token_hex(3)}"


class ReviewerProfile(TimeStampedModel):
    """Reviewer display defaults (PII-safe: minted nickname)."""

    user: "models.OneToOneField[User]" = models.OneToOneField(  # type: ignore[assignment]  # OneToOneField typing drift vs django-stubs reverse
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewer_profile",
        verbose_name=_("User"),
    )
    nickname = models.CharField(
        max_length=50,
        default=_mint_nickname,
        verbose_name=_("Nickname"),
        help_text=_(
            "Public reviewer name in Mangrove reviews; never derived from the account."
        ),
    )
    language = models.CharField(
        max_length=35,
        blank=True,
        default="",
        verbose_name=_("Preferred review language"),
        help_text=_("BCP 47 tag used as the default review language."),
    )

    objects = models.Manager()

    class Meta:  # type: ignore[assignment]  # nested Meta vs abstract base Meta: known checker limitation (Hut.Meta idiom)
        verbose_name = _("Reviewer profile")
        verbose_name_plural = _("Reviewer profiles")

    def __str__(self) -> str:
        return self.nickname


class _ActionChoices(models.TextChoices):
    review = "review", _("review")
    edit = "edit", _("edit")
    delete = "delete", _("delete")
    report_abuse = "report_abuse", _("report abuse")


class _StateChoices(models.TextChoices):
    pending = "pending", _("pending")
    accepted = "accepted", _("accepted")
    failed = "failed", _("failed")


class SubmittedReview(TimeStampedModel):
    """Append-only log of every JWT Wodore signed and relayed upstream.

    Audit/erasure/archival aid — never a serving path (reads always proxy
    the upstream API). A row is created in ``pending`` state before the
    relay and marked ``accepted``/``failed`` afterwards; deletes append a
    new ``delete`` action row (existing rows are never mutated).
    """

    Action = _ActionChoices
    State = _StateChoices

    user: "models.ForeignKey[User]" = models.ForeignKey(  # type: ignore[assignment]  # ForeignKey typing drift vs django-stubs reverse
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_reviews",
        verbose_name=_("User"),
    )
    hut_slug = models.CharField(
        max_length=50, db_index=True, verbose_name=_("Hut slug")
    )
    subject = models.CharField(max_length=255, verbose_name=_("Mangrove subject URI"))
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        default=Action.review,
        db_index=True,
        verbose_name=_("Action"),
    )
    state = models.CharField(
        max_length=10,
        choices=State.choices,
        default=State.pending,
        db_index=True,
        verbose_name=_("State"),
    )
    #: ``iat`` claim of the signed JWT (UTC).
    iat = models.DateTimeField(verbose_name=_("Issued at"))
    #: The JWT's third base64url segment — the derived signature (the
    #: upstream submit response carries none).
    signature = models.CharField(
        max_length=512, unique=True, verbose_name=_("Signature")
    )
    #: For action rows (edit/delete/report): the targeted review's
    #: signature (the ``urn:maresi:`` reference).
    target_signature = models.CharField(
        max_length=512,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Target signature"),
    )
    jwt = models.TextField(verbose_name=_("Signed JWT (verbatim)"))

    objects = models.Manager()

    class Meta:  # type: ignore[assignment]  # nested Meta vs abstract base Meta: known checker limitation (Hut.Meta idiom)
        verbose_name = _("Submitted review")
        verbose_name_plural = _("Submitted reviews")
        indexes = (
            models.Index(fields=["user", "action", "state"], name="reviews_quota_idx"),
        )
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_action_valid",
                condition=models.Q(action__in=_ActionChoices.values),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_state_valid",
                condition=models.Q(state__in=_StateChoices.values),
            ),
        )

    def __str__(self) -> str:
        return f"{self.user} {self.action} {self.signature[:16]}… ({self.state})"


class HutReviewSubject(TimeStampedModel):
    """The pinned review name (``q``) of a hut — set on FIRST review write.

    Reads resolve ``q`` dynamically (pinned name → OSM name → hut name);
    the first submitted review pins the chosen name so later OSM renames
    or hut renames cannot fork the subject (openspec reviews-mangrove D1).
    """

    hut = models.OneToOneField(
        "huts.Hut",
        on_delete=models.CASCADE,
        related_name="review_subject",
        verbose_name=_("Hut"),
    )
    name = models.CharField(
        max_length=100,
        verbose_name=_("Review name (subject q)"),
        help_text=_(
            "Pinned when the first review is written; the Mangrove subject "
            "q parameter. OSM name if available, otherwise the hut name."
        ),
    )

    objects = models.Manager()

    class Meta:  # type: ignore[assignment]  # nested Meta vs abstract base Meta: known checker limitation (Hut.Meta idiom)
        verbose_name = _("Hut review subject")
        verbose_name_plural = _("Hut review subjects")

    def __str__(self) -> str:
        return f"{self.hut}: {self.name}"


class ReviewMergeRequest(TimeStampedModel):
    """User-filed request to merge/relink a hut's reviews (admin queue).

    Just a note with a link (openspec reviews-mangrove D7): staff review
    and — once Wodore's reviewer identity is credible — file the actual
    Mangrove equivalence claims manually.
    """

    class State(models.TextChoices):
        new = "new", _("new")
        done = "done", _("done")
        rejected = "rejected", _("rejected")

    State = State

    hut = models.ForeignKey(
        "huts.Hut",
        on_delete=models.CASCADE,
        related_name="review_merge_requests",
        verbose_name=_("Hut"),
    )
    target = models.CharField(
        max_length=255,
        verbose_name=_("Merge target"),
        help_text=_("Subject URI, hut slug, or URL the reviews should merge with."),
    )
    note = models.TextField(
        max_length=2000, blank=True, default="", verbose_name=_("Note")
    )
    link = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("Link"),
        help_text=_("Supporting URL (e.g. the other listing)."),
    )
    created_by = models.ForeignKey(  # type: ignore[assignment]  # ForeignKey typing drift vs django-stubs reverse
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="review_merge_requests",
        verbose_name=_("Created by"),
    )
    state = models.CharField(
        max_length=10,
        choices=State.choices,
        default=State.new,
        db_index=True,
        verbose_name=_("State"),
    )

    objects = models.Manager()

    class Meta:  # type: ignore[assignment]  # nested Meta vs abstract base Meta: known checker limitation (Hut.Meta idiom)
        verbose_name = _("Review merge request")
        verbose_name_plural = _("Review merge requests")
        ordering = ("-created",)

    def __str__(self) -> str:
        return f"{self.hut} → {self.target[:40]} ({self.state})"


class ReviewBlacklist(TimeStampedModel):
    """Mangrove review signatures hidden from Wodore-served responses.

    A local serving decision — never mutates upstream data.
    """

    signature = models.CharField(
        max_length=512, unique=True, verbose_name=_("Signature")
    )
    reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Reason"),
    )
    created_by: "models.ForeignKey[User | None]" = models.ForeignKey(  # type: ignore[assignment]  # ForeignKey typing drift vs django-stubs reverse
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="review_blacklist_entries",
        verbose_name=_("Created by"),
    )

    objects = models.Manager()

    class Meta:  # type: ignore[assignment]  # nested Meta vs abstract base Meta: known checker limitation (Hut.Meta idiom)
        verbose_name = _("Review blacklist entry")
        verbose_name_plural = _("Review blacklist entries")

    def __str__(self) -> str:
        return self.signature[:32]


__all__ = [
    "InvalidToken",
    "HutReviewSubject",
    "ReviewerKey",
    "ReviewerProfile",
    "SubmittedReview",
    "ReviewMergeRequest",
    "ReviewBlacklist",
    "encrypt_private_jwk",
    "decrypt_private_jwk",
]
