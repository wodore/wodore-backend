"""GDPR erasure for a user's Mangrove reviews (openspec: review-identity).

Signs and relays ``delete`` actions for every review in the user's
submission log (idempotent — upstream refusals for already-deleted
targets are success), then destroys the key, profile and log rows (the
one documented exception to the log's append-only rule). The PROTECT
foreign keys make this the only sanctioned path that can delete a
user with reviews.
"""

import typing as t
from typing import override

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from server.apps.reviews import services, signing
from server.apps.reviews.client import UpstreamRejected, UpstreamUnavailable
from server.apps.reviews.models import ReviewerKey, ReviewerProfile, SubmittedReview


class Command(BaseCommand):
    """Erase one user's reviews (upstream deletes + local destruction)."""

    help = (
        "Sign and relay Mangrove delete actions for every review of the "
        "user, then destroy the reviewer key, profile and submission log."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("email", type=str, help="Account email to erase")
        parser.add_argument(
            "--export",
            type=str,
            default="",
            help="Dump the submission log to this JSONL file before erasing",
        )

    @override
    def handle(self, *args: t.Any, **options: t.Any) -> None:
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        user = user_model.objects.filter(email=options["email"]).first()
        if user is None:
            self.stderr.write(f"No user with email {options['email']}")
            raise SystemExit(1)

        key = ReviewerKey.objects.filter(user=user).first()
        rows = list(
            SubmittedReview.objects.filter(
                user=user, action=SubmittedReview.Action.review
            ).order_by("created")
        )
        self.stdout.write(
            f"Erasing {len(rows)} review(s) for {options['email']} "
            f"(key: {'present' if key else 'absent'})"
        )

        if options["export"]:
            with open(options["export"], "w") as handle:
                for row in rows:
                    import json

                    handle.write(
                        json.dumps(
                            {
                                "signature": row.signature,
                                "subject": row.subject,
                                "hut_slug": row.hut_slug,
                                "iat": row.iat.isoformat(),
                                "jwt": row.jwt,
                            }
                        )
                        + "\n"
                    )
            self.stdout.write(f"Exported log to {options['export']}")

        if key is not None:
            private_jwk = services._decrypt_key_jwk(key)
            deleted = refused = failed = 0
            for row in rows:
                if row.state != SubmittedReview.State.accepted:
                    continue  # never relayed — nothing upstream to delete
                jwt = signing.build_action_jwt(
                    key.kid,
                    private_jwk,
                    action="delete",
                    target_signature=row.signature,
                )
                try:
                    services.client().submit(jwt)
                    deleted += 1
                except UpstreamRejected:
                    # Already deleted upstream — idempotent success.
                    refused += 1
                except UpstreamUnavailable:
                    failed += 1
                    self.stderr.write(
                        f"  upstream unavailable — re-run later for signature "
                        f"{row.signature[:16]}…"
                    )
            if failed:
                self.stderr.write(
                    f"{failed} delete action(s) NOT relayed — nothing destroyed "
                    "locally; re-run the command (it is resumable)."
                )
                raise SystemExit(2)
            self.stdout.write(
                f"Delete actions relayed: {deleted} accepted, {refused} "
                "already-deleted (idempotent success)"
            )

        SubmittedReview.objects.filter(user=user).delete()
        ReviewerProfile.objects.filter(user=user).delete()
        ReviewerKey.objects.filter(user=user).delete()
        self.stdout.write(
            f"Destroyed local records for {options['email']} at "
            f"{timezone.now().isoformat()}"
        )
