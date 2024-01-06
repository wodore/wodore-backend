import sys
from typing import Any, Sequence

import click
from hut_services import BaseService, HutSourceSchema

from django.conf import settings
from django.contrib.gis.geos import Point as dbPoint
from django.core.management.base import CommandParser

from server.apps.organizations.models import Organization
from server.core import UpdateCreateStatus
from server.core.management.base import CRUDCommand

from ...models import HutSource

# SERVICES: dict[str, Type[BaseService[BaseModel]]] = settings.SERVICES


def add_hut_source_db(  # type: ignore[no-any-unimported]
    huts: Sequence[HutSourceSchema],
    organization: str,
    extern_slug: str | None = None,
) -> list[HutSource]:
    try:
        org = Organization.get_by_slug(slug=organization)
    except Organization.DoesNotExist:
        click.secho(f"Organiztion '{organization}' does not exist, add it first.", fg="red")
        sys.exit(1)
    init = HutSource.objects.filter(organization=org).count() == 0
    source_huts = []
    number = 0
    for hut in huts:
        number += 1
        shut = HutSource(
            source_id=hut.source_id,
            location=dbPoint(hut.location.lon_lat) if hut.location else None,
            organization=org,
            name=hut.name,
            source_data=hut.source_data.model_dump(by_alias=True) if hut.source_data is not None else {},
            source_properties=hut.source_properties.model_dump(by_alias=True) if hut.source_properties else {},
        )
        review_status = HutSource.ReviewStatusChoices.done if init else HutSource.ReviewStatusChoices.new
        shut, status = HutSource.add(shut, new_review_status=review_status)
        _hut_name = shut.name if len(shut.name) < 18 else shut.name[:15] + ".."
        _name = f"  Hut {number!s: <3} {'`'+shut.source_id+'`':<15} {_hut_name:<20} {'('+str(shut.organization)+')':<8}"
        click.echo(f"{_name: <48}", nl=False)
        status_color = {
            UpdateCreateStatus.updated: "yellow",
            UpdateCreateStatus.created: "green",
            UpdateCreateStatus.exists: "blue",
            UpdateCreateStatus.no_change: "bright_black",
            UpdateCreateStatus.ignored: "magenta",
        }
        click.secho(f"  ... {status.value:<8}", fg=status_color.get(status, "red"), nl=False)
        click.secho(f" (#{shut.id})", dim=True)
        source_huts.append(shut)
    return source_huts


def add_hutsources_function(
    obj: "CRUDCommand[HutSource]",
    force: bool,
    model: HutSource,
    **kwargs: Any,
) -> None:
    selected_orgs = kwargs.get("selected_organizations", [])
    limit = kwargs.get("limit", None)
    offset = kwargs.get("offset", None)
    lang = kwargs.get("lang", None)
    for org in selected_orgs:
        service_class: BaseService = settings.SERVICES.get(org, None)
        if service_class is not None:
            service = service_class
            obj.stdout.write(f"Get data from '{service.__class__.__name__}'")
            src_huts = service.get_huts_from_source(limit=limit, offset=offset, lang=lang)
            obj.stdout.write(f"Got {len(src_huts)} results back, start filling database:")
            huts = add_hut_source_db(src_huts, organization=org)
            obj.stdout.write(obj.style.SUCCESS(f"Successfully added {len(huts)} new huts"))
        else:
            obj.stdout.write(obj.style.WARNING(f"Selected organization '{org}' not supported."))


class Command(CRUDCommand[HutSource]):
    # help = ""
    model = HutSource
    model_names = "hutsources"
    add_function = add_hutsources_function
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
            help=f"Organization slug, only add this one, use 'all' to add all (possible values: {', '.join(settings.SERVICES.keys())}).",
            type=str,
            required=True,
        )
        parser.add_argument("--lang", help="Language to use (de, en, fr, it)", default="de", type=str)

    def handle(self, orgs: str, lang: str, *args: Any, **options: Any) -> None:  # type: ignore[override]
        org_list = settings.SERVICES.keys() if orgs.lower().strip() == "all" else [o.strip() for o in orgs.split(",")]
        super().handle(kwargs_add={"selected_organizations": org_list, "lang": lang}, **options)
