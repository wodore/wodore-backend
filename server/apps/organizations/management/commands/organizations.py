from pathlib import Path
from typing import Any

from django_admin_runner import register_command

from server.core.management import CRUDCommand

from ...models import Organization


@register_command(group="Organizations")
class Command(CRUDCommand[Organization]):
    help = "Manage organizations (add/update from fixture with logos, dump)."
    use_media_args = True
    model = Organization  # type: ignore  # CRUDCommand.model is TModel, needs the class (stubs drift, cf. hut_sources)
    model_names = "organizations"
    lookup_field = "slug"  # Use slug for identification, ignore fixture PKs

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        main_path = Path(self.app_label) / "logos"
        self.set_media_paths(src=Path("media"), dst=main_path)
