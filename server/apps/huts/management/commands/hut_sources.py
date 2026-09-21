import sys
from typing import Any, Sequence

import click
from hut_services import BaseService, HutSourceSchema

from django.conf import settings
from django.contrib.gis.geos import Point as dbPoint
from django.core.management.base import CommandParser
from django_admin_runner import register_command

from server.apps.organizations.models import Organization
from server.core import UpdateCreateStatus
from server.core.management.base import CRUDCommand

from ...models import HutSource

# SERVICES: dict[str, Type[BaseService[BaseModel]]] = settings.SERVICES


def add_hut_source_db(  # type: ignore[no-any-unimported]
    huts: Sequence[HutSourceSchema],
    organization: str,
    extern_slug: str | None = None,
) -> tuple[int, int, int, int]:
    try:
        org = Organization.get_by_slug(slug=organization)
    except Organization.DoesNotExist:
        click.secho(
            f"Organization '{organization}' does not exist, add it first.", fg="red"
        )
        sys.exit(1)
    init = HutSource.objects.filter(organization=org).count() == 0
    source_huts = []
    number = 0
    counter = {
        UpdateCreateStatus.updated: 0,
        UpdateCreateStatus.created: 0,
        UpdateCreateStatus.exists: 0,
        UpdateCreateStatus.no_change: 0,
        UpdateCreateStatus.ignored: 0,
    }
    for hut in huts:
        number += 1
        shut = HutSource(
            source_id=hut.source_id,
            location=dbPoint(hut.location.lon_lat) if hut.location else None,
            organization=org,
            name=hut.name,
            source_data=hut.source_data.model_dump(by_alias=True)
            if hut.source_data is not None
            else {},
            source_properties=hut.source_properties.model_dump(by_alias=True)
            if hut.source_properties
            else {},
        )
        review_status = (
            HutSource.ReviewStatusChoices.done
            if init
            else HutSource.ReviewStatusChoices.new
        )
        shut, status = HutSource.add(shut, new_review_status=review_status)
        _hut_name = shut.name if len(shut.name) < 18 else shut.name[:15] + ".."
        _name = f"  Hut {number!s: <3} {'`' + shut.source_id + '`':<15} {_hut_name:<20} {'(' + str(shut.organization) + ')':<8}"
        click.echo(f"{_name: <48}", nl=False)
        status_color = {
            UpdateCreateStatus.updated: "yellow",
            UpdateCreateStatus.created: "green",
            UpdateCreateStatus.exists: "blue",
            UpdateCreateStatus.no_change: "bright_black",
            UpdateCreateStatus.ignored: "magenta",
        }
        counter[status] += 1
        click.secho(
            f"  ... {status.value:<8}", fg=status_color.get(status, "red"), nl=False
        )
        click.secho(f" (#{shut.id})", dim=True)  # pyright: ignore[reportAttributeAccessIssue]  # noqa: E501 — auto pk, plugin-less Pyright
        source_huts.append(shut)
    added = counter[UpdateCreateStatus.created]
    updated = counter[UpdateCreateStatus.updated]
    nochange = (
        counter[UpdateCreateStatus.exists] + counter[UpdateCreateStatus.no_change]
    )
    failed = counter[UpdateCreateStatus.ignored]
    return added, updated, nochange, failed


def add_hutsources_function(
    obj: "CRUDCommand[HutSource]",
    force: bool,
    model: HutSource,
    **kwargs: Any,
) -> None:
    selected_orgs = kwargs.get("selected_organizations", [])
    limit = kwargs.get("limit") or 0  # 0 = all
    offset = kwargs.get("offset") or 0
    lang = kwargs.get("lang")
    with_minisite = kwargs.get("with_minisite", False)
    for org in selected_orgs:
        service_class: BaseService = settings.SERVICES.get(org, None)
        if service_class is not None:
            service = service_class
            obj.stdout.write(f"Get data from '{service.__class__.__name__}'")
            src_huts = service.get_huts_from_source(
                limit=limit, offset=offset, lang=lang, with_minisite=with_minisite
            )
            obj.stdout.write(
                f"Got {len(src_huts)} results back, start filling database:"
            )
            added, updated, nochange, failed = add_hut_source_db(
                src_huts, organization=org
            )
            if added:
                obj.stdout.write(
                    obj.style.SUCCESS(
                        f"Successfully added {added} new hut source{'s' if added > 1 else ''}"
                    )
                )
            if updated:
                obj.stdout.write(
                    obj.style.SUCCESS(
                        f"Successfully updated {updated} hut source{'s' if updated > 1 else ''}"
                    )
                )
            if nochange:
                obj.stdout.write(
                    obj.style.NOTICE(
                        f"No change for {nochange} hut source{'s' if updated > 1 else ''}"
                    )
                )
            if failed:
                obj.stdout.write(
                    obj.style.ERROR(
                        f"Failed to add {failed} hut source{'s' if failed > 1 else ''}"
                    )
                )
        else:
            obj.stdout.write(
                obj.style.WARNING(f"Selected organization '{org}' not supported.")
            )


@register_command(group="Huts")
class Command(CRUDCommand[HutSource]):
    # help = ""
    model = HutSource  # pyright: ignore[reportAssignmentType] — CRUDCommand convention: class assigned to `model`
    model_names = "hutsources"
    add_function = add_hutsources_function  # pyright: ignore[reportAssignmentType] — see `model`
    use_limit_arg = True
    use_offset_arg = True
    # use_update_arg = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.add_argument(
            "-O",
            "--orgs",
            "--organizations",
            help=(
                "Hut source organizations: single slug, comma separated list, "
                f"or 'all' (possible values: {', '.join(settings.SERVICES.keys())})."
            ),
            type=str,
            required=True,
        )
        parser.add_argument(
            "--lang",
            help="Language to use",
            default="de",
            choices=["de", "en", "fr", "it"],
            type=str,
        )
        parser.add_argument(
            "-m",
            "--with-minisite",
            action="store_true",
            help=(
                "Additionally fetch each hut's minisite info box "
                "(FFCAM: guarded/winter bed totals and contacts; "
                "1 request per hut, cached)."
            ),
        )

    def handle(
        self, orgs: str, lang: str, with_minisite: bool, *args: Any, **options: Any
    ) -> None:  # type: ignore[override]
        if orgs.lower().strip() == "all":
            org_list = list(settings.SERVICES.keys())
        else:
            org_list = [o.strip() for o in orgs.split(",")]
            unknown = [o for o in org_list if o not in settings.SERVICES]
            if unknown:
                self.stdout.write(
                    self.style.ERROR(
                        f"Unknown organization(s): {', '.join(unknown)}. "
                        f"Possible values: {', '.join(settings.SERVICES.keys())}"
                    )
                )
                sys.exit(1)
        super().handle(
            kwargs_add={
                "selected_organizations": org_list,
                "lang": lang,
                "with_minisite": with_minisite,
            },
            **options,
        )
