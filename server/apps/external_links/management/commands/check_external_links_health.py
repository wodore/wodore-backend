from django.core.management.base import BaseCommand
from django.db import models
from django.utils import timezone
from datetime import timedelta

from server.apps.external_links.models import ExternalLink


class Command(BaseCommand):
    help = "Check health of external links"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=1,
            help="Only check links not checked in the last N days (default: 1)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Check all links regardless of last check time",
        )
        parser.add_argument(
            "--failed-only",
            action="store_true",
            help="Only check links that have failed previously",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of links to check",
        )

    def handle(self, *args, **options):
        days = options["days"]
        check_all = options["all"]
        failed_only = options["failed_only"]
        limit = options["limit"]

        # Build queryset
        queryset = ExternalLink.objects.filter(is_active=True)

        if not check_all:
            cutoff = timezone.now() - timedelta(days=days)
            queryset = queryset.filter(
                models.Q(last_checked__isnull=True) | models.Q(last_checked__lt=cutoff)
            )

        if failed_only:
            queryset = queryset.filter(failure_count__gt=0)

        if limit:
            queryset = queryset[:limit]

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No links to check."))
            return

        self.stdout.write(f"Checking health of {total} external links...")

        checked = 0
        success = 0
        failed = 0
        errors = []

        for link in queryset:
            checked += 1
            self.stdout.write(
                f"[{checked}/{total}] Checking {link.identifier}: {link.url_i18n}",
                ending="\r",
            )

            try:
                result = link.check_health()
                link.save(
                    update_fields=["last_checked", "response_code", "failure_count"]
                )

                if result.get("success"):
                    success += 1
                    status = f"✓ {result['status_code']}"
                else:
                    failed += 1
                    status = f"✗ {result.get('error', 'Unknown error')}"
                    errors.append(
                        {
                            "identifier": link.identifier,
                            "url": link.url_i18n,
                            "error": result.get("error"),
                        }
                    )

                self.stdout.write(f"[{checked}/{total}] {link.identifier}: {status}")

            except Exception as e:
                failed += 1
                self.stdout.write(
                    self.stdout.style.ERROR(
                        f"[{checked}/{total}] {link.identifier}: ✗ Exception: {str(e)}"
                    )
                )
                errors.append(
                    {
                        "identifier": link.identifier,
                        "url": link.url_i18n,
                        "error": str(e),
                    }
                )

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Health check complete!"))
        self.stdout.write(f"Total checked: {checked}")
        self.stdout.write(f"Success: {self.style.SUCCESS(str(success))}")
        self.stdout.write(f"Failed: {self.style.ERROR(str(failed))}")

        if errors:
            self.stdout.write("\nFailed links:")
            for error in errors:
                self.stdout.write(
                    f"  - {error['identifier']}: {error['url']}"
                    f"\n    Error: {error['error']}"
                )
