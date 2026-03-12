from pathlib import Path

from server.core.management import CRUDCommand

from ...models import Organization


class Command(CRUDCommand):
    # help = ""
    use_media_args = True
    model = Organization
    model_names = "organizations"
    lookup_field = "slug"  # Use slug for identification, ignore fixture PKs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        main_path = Path(self.app_label) / "logos"
        self.set_media_paths(src=Path("media"), dst=main_path)
