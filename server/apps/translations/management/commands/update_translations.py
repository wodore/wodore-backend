"""Fill empty translated fields (Hut, GeoPlace) using an LLM.

Examples:

    app update_translations --hut cabane-de-tracuit
    app update_translations --geoplace zermatt --languages fr,it
    app update_translations --model hut --all --limit 20
    app update_translations --model geoplace --all --languages en --dry-run
"""

import typing as t

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut
from server.apps.translations.llm import TranslationClient, TranslationError
from server.apps.translations.service import translate_instance


class Command(BaseCommand):
    help = (
        "Translate empty translated fields (name/description/note) of huts "
        "and geoplaces from each record's main language using an LLM. "
        "Existing translations are never touched unless --overwrite is set."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--hut",
            action="append",
            default=[],
            metavar="SLUG",
            help="Translate a single hut by slug (repeatable)",
        )
        parser.add_argument(
            "--geoplace",
            action="append",
            default=[],
            metavar="SLUG",
            help="Translate a single geoplace by slug (repeatable)",
        )
        parser.add_argument(
            "--model",
            choices=["hut", "geoplace"],
            help="Model to process when using --all",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Process all instances of --model (mind the API costs)",
        )
        parser.add_argument(
            "--languages",
            help="Comma-separated target language codes "
            f"(default: all of {','.join(settings.LANGUAGE_CODES)} except "
            "the record's main language)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Stop after N instances (bulk cost control)",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Also replace existing translations",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be translated without saving",
        )

    def handle(self, *args: t.Any, **options: t.Any) -> None:
        hut_slugs: list[str] = options["hut"]
        geoplace_slugs: list[str] = options["geoplace"]
        languages = self._parse_languages(options["languages"])

        queryset = self._build_queryset(hut_slugs, geoplace_slugs, options)
        if queryset is None:
            return

        try:
            client = TranslationClient()
        except Exception as error:  # surface config errors nicely
            if options["dry_run"]:
                self.stdout.write(
                    self.style.WARNING(f"{error} (dry-run continues without API)")
                )
                client = None
            else:
                raise CommandError(str(error)) from error

        limit: int | None = options["limit"]
        translated_total = 0
        errors = 0
        processed = 0
        for obj in queryset:
            if limit is not None and processed >= limit:
                break
            processed += 1
            try:
                stats = translate_instance(
                    obj,
                    languages=languages,
                    overwrite=options["overwrite"],
                    dry_run=options["dry_run"],
                    client=client,
                )
            except TranslationError as error:
                errors += 1
                self.stdout.write(self.style.ERROR(f"{obj.slug}: {error}"))
                continue
            translated_total += sum(
                len(fields) for fields in stats["translated"].values()
            )
            self._report(obj, stats, dry_run=options["dry_run"])

        summary = f"\n{processed} instance(s) processed, {translated_total} field(s) translated"
        if errors:
            summary += f", {errors} error(s)"
        self.stdout.write(self.style.SUCCESS(summary))

    def _parse_languages(self, raw: str | None) -> list[str] | None:
        if not raw:
            return None
        languages = [lang.strip() for lang in raw.split(",") if lang.strip()]
        unknown = [lang for lang in languages if lang not in settings.LANGUAGE_CODES]
        if unknown:
            raise CommandError(
                f"Unknown language(s): {', '.join(unknown)}. "
                f"Configured: {', '.join(settings.LANGUAGE_CODES)}"
            )
        return languages

    def _build_queryset(
        self,
        hut_slugs: list[str],
        geoplace_slugs: list[str],
        options: dict[str, t.Any],
    ) -> QuerySet | None:
        all_flag: bool = options["all"]
        model: str | None = options["model"]
        if all_flag and not model:
            raise CommandError("--all requires --model (hut or geoplace)")
        if not (hut_slugs or geoplace_slugs or all_flag):
            raise CommandError(
                "Nothing to do: pass --hut SLUG, --geoplace SLUG or --model MODEL --all"
            )
        # geoplace before hut: geoplaces vastly outnumber huts, process
        # cheap records first when both are requested.
        if geoplace_slugs or (all_flag and model == "geoplace"):
            qs: QuerySet = GeoPlace.objects.order_by("id")
            if geoplace_slugs:
                qs = qs.filter(slug__in=geoplace_slugs)
            self._check_found(qs, geoplace_slugs, "geoplace")
            return qs
        qs = Hut.objects.order_by("id")
        if hut_slugs:
            qs = qs.filter(slug__in=hut_slugs)
        self._check_found(qs, hut_slugs, "hut")
        return qs

    def _check_found(self, queryset: QuerySet, slugs: list[str], label: str) -> None:
        if slugs:
            found = set(queryset.values_list("slug", flat=True))
            missing = [slug for slug in slugs if slug not in found]
            if missing:
                raise CommandError(f"{label}(s) not found: {', '.join(missing)}")

    def _report(self, obj: t.Any, stats: dict[str, t.Any], dry_run: bool) -> None:
        label = f"{obj._meta.model_name} '{obj.slug}'"
        parts = []
        for lang, fields in stats["translated"].items():
            parts.append(f"{lang}: {'+'.join(fields)}")
        if parts:
            mode = "would translate" if dry_run else "translated"
            suffix = "" if dry_run else " (saved)"
            self.stdout.write(
                self.style.SUCCESS(f"{label}: {mode} {', '.join(parts)}{suffix}")
            )
        elif stats["skipped_existing"] and not stats["translated"]:
            self.stdout.write(f"{label}: nothing to do (translations exist)")
        elif stats["skipped_no_source"] and not stats["translated"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{label}: no source texts in main language "
                    f"'{stats['source_lang']}'"
                )
            )
        else:
            self.stdout.write(f"{label}: nothing to do")
        for lang, field, length in stats["too_long"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{label}: skipped {field}_{lang} "
                    f"({length} chars exceeds field limit)"
                )
            )
