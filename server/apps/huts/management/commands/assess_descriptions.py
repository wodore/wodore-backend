"""Score hut descriptions (main language) with an LLM quality rubric.

Descriptions scoring below the review threshold move `done` huts back to
`rework` so they surface in the existing review workflow. Empty
descriptions and already-scored huts are skipped by default.

Examples:

    app assess_descriptions --hut cabane-de-tracuit
    app assess_descriptions --all --limit 20
    app assess_descriptions --all --rescore --review-below 4
"""

import typing as t

from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

from server.apps.huts.models import Hut
from server.apps.translations.llm import TranslationClient, TranslationError
from server.apps.translations.service import assess_instance


class Command(BaseCommand):
    help = (
        "Assess the quality (1-10) of hut descriptions in their main "
        "language using an LLM rubric. Low scores re-open 'done' huts as "
        "'rework'. Existing scores are kept unless --rescore is set."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--hut",
            action="append",
            default=[],
            metavar="SLUG",
            help="Assess a single hut by slug (repeatable)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Assess all huts (unscored only, unless --rescore)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Stop after N huts (bulk cost control)",
        )
        parser.add_argument(
            "--rescore",
            action="store_true",
            help="Re-assess huts that already have a score",
        )
        parser.add_argument(
            "--review-below",
            type=int,
            metavar="N",
            help="Move 'done' huts scoring below N to 'rework' "
            "(default: TRANSLATION_QUALITY_REVIEW_THRESHOLD, 5)",
        )

    def handle(self, *args: t.Any, **options: t.Any) -> None:
        hut_slugs: list[str] = options["hut"]
        if not (hut_slugs or options["all"]):
            raise CommandError("Nothing to do: pass --hut SLUG or --all")

        queryset = self._build_queryset(hut_slugs, options)

        try:
            client = TranslationClient()
        except Exception as error:  # surface config errors nicely
            raise CommandError(str(error)) from error

        limit: int | None = options["limit"]
        review_below: int | None = options["review_below"]
        processed = 0
        assessed = 0
        reworked = 0
        errors = 0
        for hut in queryset:
            if limit is not None and processed >= limit:
                break
            processed += 1
            try:
                stats = assess_instance(
                    hut,
                    rescore=options["rescore"],
                    review_below=review_below,
                    client=client,
                )
            except TranslationError as error:
                errors += 1
                self.stdout.write(self.style.ERROR(f"{hut.slug}: {error}"))
                continue
            if stats.get("skipped"):
                reason = (
                    "empty description"
                    if stats["skipped"] == "empty"
                    else "already scored"
                )
                self.stdout.write(f"{hut.slug}: skipped ({reason})")
                continue
            assessed += 1
            line = f"{hut.slug}: {stats['score']}/10 — {stats['summary']}"
            if stats["rework"]:
                reworked += 1
                self.stdout.write(self.style.WARNING(f"{line} → rework"))
            else:
                self.stdout.write(self.style.SUCCESS(line))

        summary = (
            f"\n{processed} hut(s) processed, {assessed} assessed, "
            f"{reworked} moved to rework"
        )
        if errors:
            summary += f", {errors} error(s)"
        self.stdout.write(self.style.SUCCESS(summary))

    def _build_queryset(
        self, hut_slugs: list[str], options: dict[str, t.Any]
    ) -> QuerySet:
        qs: QuerySet = Hut.objects.order_by("id")
        if not options["rescore"]:
            qs = qs.filter(description_quality__isnull=True)
        if hut_slugs:
            qs = qs.filter(slug__in=hut_slugs)
            found = set(qs.values_list("slug", flat=True))
            missing = [slug for slug in hut_slugs if slug not in found]
            if missing:
                raise CommandError(f"hut(s) not found: {', '.join(missing)}")
        return qs
