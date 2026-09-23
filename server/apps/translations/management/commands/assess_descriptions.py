"""Score hut/geoplace descriptions (main language) with an LLM quality rubric.

Descriptions scoring below the review threshold move `done` records back
to `rework` so they surface in the existing review workflow. Empty
descriptions and already-scored records are skipped by default.

Examples:

    app assess_descriptions --hut cabane-de-tracuit
    app assess_descriptions --geoplace zermatt
    app assess_descriptions --model hut --all --limit 20
    app assess_descriptions --model geoplace --all --rescore --review-below 4
"""

import typing as t

from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut
from server.apps.translations.llm import TranslationClient, TranslationError
from server.apps.translations.service import assess_instance

_MODEL_CHOICES = {"hut": Hut, "geoplace": GeoPlace}


class Command(BaseCommand):
    help = (
        "Assess the quality (1-10) of hut and geoplace descriptions in "
        "their main language using an LLM rubric. Low scores re-open "
        "'done' records as 'rework'. Existing scores are kept unless "
        "--rescore is set."
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
            "--geoplace",
            action="append",
            default=[],
            metavar="SLUG",
            help="Assess a single geoplace by slug (repeatable)",
        )
        parser.add_argument(
            "--model",
            choices=sorted(_MODEL_CHOICES),
            help="Model to process when using --all",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Process all records of --model (unscored only, unless --rescore)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Stop after N records (bulk cost control)",
        )
        parser.add_argument(
            "--rescore",
            action="store_true",
            help="Re-assess records that already have a score",
        )
        parser.add_argument(
            "--review-below",
            type=int,
            metavar="N",
            help="Move 'done' records scoring below N to 'rework' "
            "(default: TRANSLATION_QUALITY_REVIEW_THRESHOLD, 5)",
        )

    def handle(self, *args: t.Any, **options: t.Any) -> None:
        hut_slugs: list[str] = options["hut"]
        geoplace_slugs: list[str] = options["geoplace"]
        if not (hut_slugs or geoplace_slugs or options["all"]):
            raise CommandError(
                "Nothing to do: pass --hut SLUG, --geoplace SLUG or --model MODEL --all"
            )

        model_label, model = self._select_model(hut_slugs, geoplace_slugs, options)
        queryset = self._build_queryset(
            model, model_label, hut_slugs, geoplace_slugs, options
        )

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
        for obj in queryset:
            if limit is not None and processed >= limit:
                break
            processed += 1
            try:
                stats = assess_instance(
                    obj,
                    rescore=options["rescore"],
                    review_below=review_below,
                    client=client,
                )
            except TranslationError as error:
                errors += 1
                self.stdout.write(self.style.ERROR(f"{obj.slug}: {error}"))
                continue
            if stats.get("skipped"):
                reason = (
                    "empty description"
                    if stats["skipped"] == "empty"
                    else "already scored"
                )
                self.stdout.write(f"{obj.slug}: skipped ({reason})")
                continue
            assessed += 1
            line = f"{obj.slug}: {stats['score']}/10 — {stats['summary']}"
            if stats["rework"]:
                reworked += 1
                self.stdout.write(self.style.WARNING(f"{line} → rework"))
            else:
                self.stdout.write(self.style.SUCCESS(line))

        summary = (
            f"\n{processed} {model_label}(s) processed, {assessed} assessed, "
            f"{reworked} moved to rework"
        )
        if errors:
            summary += f", {errors} error(s)"
        self.stdout.write(self.style.SUCCESS(summary))

    def _select_model(
        self,
        hut_slugs: list[str],
        geoplace_slugs: list[str],
        options: dict[str, t.Any],
    ) -> tuple[str, type]:
        all_flag: bool = options["all"]
        model_label: str | None = options["model"]
        if all_flag and not model_label:
            raise CommandError("--all requires --model (hut or geoplace)")
        if model_label:
            # Reject cross-model selector combinations: they would otherwise
            # silently widen to the full model (e.g. `--model hut --geoplace
            # X` would assess ALL unscored huts).
            other = geoplace_slugs if model_label == "hut" else hut_slugs
            if other:
                wrong = "--geoplace" if model_label == "hut" else "--hut"
                raise CommandError(
                    f"--model {model_label} cannot be combined with {wrong} selectors"
                )
            return model_label, _MODEL_CHOICES[model_label]
        if hut_slugs and geoplace_slugs:
            raise CommandError(
                "--hut and --geoplace selectors cannot be mixed; "
                "run one model at a time or use --model MODEL --all"
            )
        if geoplace_slugs:
            return "geoplace", GeoPlace
        return "hut", Hut

    def _build_queryset(
        self,
        model: type,
        model_label: str,
        hut_slugs: list[str],
        geoplace_slugs: list[str],
        options: dict[str, t.Any],
    ) -> QuerySet:
        qs: QuerySet = model.objects.order_by("id")
        if not options["rescore"]:
            qs = qs.filter(description_quality__isnull=True)
        slugs = geoplace_slugs if model_label == "geoplace" else hut_slugs
        if slugs:
            qs = qs.filter(slug__in=slugs)
            found = set(qs.values_list("slug", flat=True))
            missing = [slug for slug in slugs if slug not in found]
            if missing:
                raise CommandError(f"{model_label}(s) not found: {', '.join(missing)}")
        return qs
