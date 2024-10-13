from pathlib import Path

from server.core.management import CRUDCommand

from ...models import HutType


class Command(CRUDCommand):
    # help = ""
    use_media_args = True
    model = HutType
    model_names = "huttypes"
    compare_fields = ("slug",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        main_path = Path(self.app_label) / "types"
        self.set_media_paths(src=Path("media"), dst=main_path)
