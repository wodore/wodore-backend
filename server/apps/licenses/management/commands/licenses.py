from typing import Any

from django_admin_runner import register_command

from server.core.management import CRUDCommand

from ...models import License


@register_command(group="Licenses")
class Command(CRUDCommand[License]):
    help = "Manage licenses (add/update from fixture, dump)."
    use_media_args = True
    model = License  # type: ignore  # CRUDCommand.model is TModel, needs the class (stubs drift, cf. hut_sources)
    model_names = "licenses"
    compare_fields = ("slug",)
    lookup_field = "slug"  # Use slug for identification, ignore fixture PKs

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    # def handle(self, *args, **options):
    #    super().handle(**options)
