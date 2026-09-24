"""Score hut/geoplace descriptions (main language) with an LLM quality rubric.

Descriptions scoring below the rework threshold move `done` records back
to `rework` so they surface in the existing review workflow. Empty
descriptions and already-scored records are skipped by default.

Examples:

    app assess_descriptions --hut cabane-de-tracuit
    app assess_descriptions --geoplace zermatt
    app assess_descriptions --model hut --all --limit 20
    app assess_descriptions --model geoplace --all --rescore --rework-below 4
"""

import typing as t

from django_admin_runner import register_command
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut
from server.apps.translations.llm import (
    TranslationClient,
    TranslationError,
    translations_api_enabled,
)
from server.apps.translations.service import assess_instance

_MODEL_CHOICES = {"hut": Hut, "geoplace": GeoPlace}

# rich markup colors per report level (see _report_line)
_LEVEL_COLORS = {"success": "green", "warning": "yellow", "error": "red"}


# Admin-runner registration is import-time (the package registry has no
# unregister); unconfigured environments register a no-op so the command
# stays absent from the admin while remaining fully available on the CLI.
_register = (
    register_command(group="Translations", models=[Hut, GeoPlace])
    if translations_api_enabled()
    else (lambda cls: cls)
)


@_register
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
            "--rework-below",
            type=int,
            metavar="N",
            dest="rework_below",
            help="Move 'done' records scoring below N to 'rework' "
            "(default: TRANSLATION_QUALITY_REVIEW_THRESHOLD, 5)",
        )
        parser.add_argument(
            "--no-progress",
            action="store_true",
            help="Disable the progress bar and print results as they "
            "complete (useful for cron jobs)",
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
        total = queryset.count() if limit is None else min(limit, queryset.count())

        if options["no_progress"]:
            # Plain mode: results printed as they complete.
            emit = self._emit_plain
            self._run(queryset, limit, options, client, model_label, emit, None)
        else:
            with Progress(
                SpinnerColumn(finished_text="✓"),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("•"),
                TimeElapsedColumn(),
            ) as progress:
                task = progress.add_task(
                    f"[cyan]Assessing {model_label} descriptions...",
                    total=total,
                )
                emit = self._emit_rich(progress)
                self._run(
                    queryset,
                    limit,
                    options,
                    client,
                    model_label,
                    emit,
                    (progress, task),
                )

    def _run(
        self,
        queryset: QuerySet,
        limit: int | None,
        options: dict[str, t.Any],
        client: TranslationClient,
        model_label: str,
        emit: t.Callable[[str, str], None],
        progress: tuple[Progress, t.Any] | None,
    ) -> None:
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
                    rework_below=options["rework_below"],
                    client=client,
                )
            except TranslationError as error:
                errors += 1
                emit(f"{obj.slug}: {error}", "error")
                continue
            if progress is not None:
                progress[0].advance(progress[1])
            if stats.get("skipped"):
                reason = (
                    "empty description"
                    if stats["skipped"] == "empty"
                    else "already scored"
                )
                emit(f"{obj.slug}: skipped ({reason})", "plain")
                continue
            assessed += 1
            line = f"{obj.slug}: {stats['score']}/10 — {stats['summary']}"
            if stats["rework"]:
                reworked += 1
                emit(f"{line} → rework", "warning")
            else:
                emit(line, "success")

        summary = (
            f"\n{processed} {model_label}(s) processed, {assessed} assessed, "
            f"{reworked} moved to rework"
        )
        if errors:
            summary += f", {errors} error(s)"
        self.stdout.write(self.style.SUCCESS(summary))

    def _emit_plain(self, line: str, level: str) -> None:
        writer = {
            "success": self.style.SUCCESS,
            "warning": self.style.WARNING,
            "error": self.style.ERROR,
        }.get(level)
        self.stdout.write(writer(line) if writer else line)

    def _emit_rich(self, progress: Progress) -> t.Callable[[str, str], None]:
        def emit(line: str, level: str) -> None:
            color = _LEVEL_COLORS.get(level)
            if color:
                progress.console.print(f"[{color}]{line}[/{color}]")
            else:
                progress.console.print(line)

        return emit

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
