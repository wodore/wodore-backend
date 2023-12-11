from pathlib import Path
from ...models import Organization
from server.core.management import CRUDCommand


class Command(CRUDCommand):
    # help = ""
    use_media_args = True
    model = Organization
    model_names = "organizations"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        main_path = Path(self.app_label) / "logos"
        self.set_media_paths(src=Path("media") / main_path, dst=main_path)

    # def handle(self, *args, **options):
    #    super().handle(**options)
